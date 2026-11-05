"""Versão Azure: login Microsoft (Easy Auth), saúde, carga da planilha pela web e cópia no SharePoint."""
import base64
import io
import json
import os
from pathlib import Path

import httpx
import pytest

RAIZ = Path(__file__).resolve().parent.parent
os.environ.update(MODO_DEMO="true", URL_BASE="http://testserver", SEGREDO_APP="teste",
                  DATABASE_URL=f"sqlite:///{RAIZ / 'data' / 'teste.db'}",
                  PASTA_ARQUIVOS=str(RAIZ / "data" / "teste_arquivos"))

from fastapi.testclient import TestClient  # noqa: E402

from app import config, sharepoint  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Documento, Historico, Nota, SessionLocal, Status  # noqa: E402


@pytest.fixture
def cli():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def login(monkeypatch):
    monkeypatch.setattr(config.settings(), "login_obrigatorio", True)
    monkeypatch.setattr(config.settings(), "usuarios_permitidos", "renan@commcenter.com.br, @financeiro.commcenter.com.br")


def _cab(email, nome="Fulano"):
    principal = {"claims": [{"typ": "preferred_username", "val": email}, {"typ": "name", "val": nome}]}
    return {"X-MS-CLIENT-PRINCIPAL-NAME": email,
            "X-MS-CLIENT-PRINCIPAL": base64.b64encode(json.dumps(principal).encode()).decode()}


def test_saude(cli):
    assert cli.get("/saude").json() == {"ok": True}


def test_login_microsoft(cli, login):
    r = cli.get("/fornecedores", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/.auth/login/aad?post_login_redirect_uri=%2Ffornecedores")
    assert cli.get("/saude").status_code == 200  # health check do Azure sem login

    r = cli.get("/", headers=_cab("Renan@commcenter.com.br"))
    assert r.status_code == 200 and "renan@commcenter.com.br" in r.text and "/.auth/logout" in r.text
    assert cli.get("/", headers=_cab("ana@financeiro.commcenter.com.br")).status_code == 200
    assert cli.get("/", headers=_cab("estagio@commcenter.com.br")).status_code == 403
    # Cabeçalho antigo e nome digitado não valem com login ligado
    assert cli.post("/usuario", data={"nome": "x"}, headers=_cab("renan@commcenter.com.br")).status_code == 403


def test_aprovador_fora_da_lista_abre_link_assinado(cli, login):
    from app.aprovacao import assinatura
    with SessionLocal() as db:
        n = Nota(status=Status.AGUARDANDO, prestador="TESTE", numero="1", aprovadores="rbastos@commcenter.com.br")
        db.add(n)
        db.commit()
        nid = n.id
    e = "rbastos@commcenter.com.br"
    url = f"/aprovacao/{nid}?e={e}&s={assinatura(nid, e)}"
    assert cli.get(url, follow_redirects=False).status_code == 302  # precisa logar
    assert cli.get(url, headers=_cab(e)).status_code == 200  # não está em USUARIOS_PERMITIDOS, mas é aprovador
    cli.post(f"/aprovacao/{nid}", data={"e": e, "s": assinatura(nid, e), "acao": "aprovar"}, headers=_cab(e))
    with SessionLocal() as db:
        assert db.get(Nota, nid).status == Status.APROVADA


def test_carga_da_planilha_pela_web(cli, monkeypatch, tmp_path):
    from openpyxl import Workbook
    monkeypatch.setattr(config.settings(), "pasta_dados", tmp_path)
    wb = Workbook()
    infos = wb.active
    infos.title = "Infos"
    infos.append(["COD AXT", "COD VMT", "APELIDO", "NOME", "CNPJ", "EMPRESA"])
    infos.append([None, None, "!FILIAL", "VMT 99", "05.828.732/0065-52", None])
    infos.append([None, "ZTEST1", "ACME", "ACME SERVICOS LTDA", "99.888.777/0001-66", "VMT"])
    mes = wb.create_sheet("Outubro 26")
    mes.append(["DESPESA", "EMPRESA", "PRESTADOR", "DESCRIÇÃO", "FILIAL", "PRODUTO", "CC", "CONTA CONTABIL",
                "FORNECEDOR", "VALOR", "NFS"])
    mes.append(["OPEX", "VMT", "ACME", "Suporte", 99, "S_1.07", 9915, 413337, "ZTEST1", 100.0, 77])
    buf = io.BytesIO()
    wb.save(buf)
    try:
        r = cli.post("/carga", files={"arquivo": ("Notas.xlsx", buf.getvalue())}, follow_redirects=False)
        assert r.status_code == 303 and "Importado: 1 filiais" in r.cookies.get("flash", "")
        assert (tmp_path / "config" / "fornecedores.csv").exists()
        assert config.filial_por_cnpj("05828732006552")["filial"] == "99"
        with SessionLocal() as db:
            assert db.query(Historico).filter(Historico.prestador == "ACME").count() == 1
        assert cli.get("/carga").status_code == 200
    finally:
        monkeypatch.undo()
        config.recarregar_config()


def test_cliente_sharepoint_rest(monkeypatch):
    chamadas = []

    def responder(req: httpx.Request) -> httpx.Response:
        chamadas.append((req.method, req.url.path))
        if req.url.path.endswith("/sites/comm.sharepoint.com:/sites/PCTI"):
            return httpx.Response(200, json={"id": "site1"})
        if req.url.path.endswith("/sites/site1/drives"):
            return httpx.Response(200, json={"value": [{"name": "Documentos", "id": "drv"}]})
        if req.method == "PUT":
            return httpx.Response(201, json={"id": "it1", "webUrl": "https://comm.sharepoint.com/x.pdf"})
        return httpx.Response(204)

    monkeypatch.setattr(config.settings(), "sharepoint_site", "comm.sharepoint.com:/sites/PCTI")
    sp = sharepoint.SharePoint(lambda: "tok", httpx.Client(transport=httpx.MockTransport(responder)))
    assert sp.enviar("AXT/2026-11/TOTVS_NF_1_AXT.pdf", b"%PDF")["id"] == "it1"
    assert chamadas[-1] == ("PUT", "/v1.0/drives/drv/root:/Notas/AXT/2026-11/TOTVS_NF_1_AXT.pdf:/content")
    sp.excluir("velho")
    assert chamadas[-1] == ("DELETE", "/v1.0/drives/drv/items/velho")


def test_sincroniza_arquivos_renomeados(cli, monkeypatch, tmp_path):
    monkeypatch.setattr(config.settings(), "sharepoint_site", "demo")
    demo = sharepoint.SharePointDemo()
    demo.pasta = tmp_path / "Notas"
    monkeypatch.setattr(sharepoint, "_cliente", demo)
    pasta = config.settings().pasta_arquivos / "AXT" / "2026-11"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "ZZ_NF_9_AXT.pdf").write_bytes(b"%PDF-teste")
    with SessionLocal() as db:
        n = Nota(status=Status.AGUARDANDO, prestador="ZZ", numero="9", empresa="AXT")
        db.add(n)
        db.flush()
        db.add(Documento(nota_id=n.id, tipo="NF", nome_original="nf.pdf", nome_final="ZZ_NF_9_AXT.pdf",
                         caminho=str(pasta / "ZZ_NF_9_AXT.pdf"), sha256="x"))
        db.commit()
        nid = n.id
    assert sharepoint.sincronizar_pendentes()["enviados"] >= 1
    assert (tmp_path / "Notas" / "AXT" / "2026-11" / "ZZ_NF_9_AXT.pdf").read_bytes() == b"%PDF-teste"
    with SessionLocal() as db:
        n = db.get(Nota, nid)
        assert n.pasta_sharepoint and n.documentos[0].sharepoint_nome == "ZZ_NF_9_AXT.pdf"
    assert sharepoint.sincronizar_pendentes()["enviados"] == 0  # nada pendente
