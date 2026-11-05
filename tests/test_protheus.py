"""Integração Protheus: montagem do JSON, leitura das respostas e cliente REST (com transporte simulado)."""
import json
import os
from datetime import date, datetime
from pathlib import Path

import httpx
import pytest

RAIZ = Path(__file__).resolve().parent.parent
os.environ.update(MODO_DEMO="true", URL_BASE="http://testserver", SEGREDO_APP="teste",
                  DATABASE_URL=f"sqlite:///{RAIZ / 'data' / 'teste.db'}",
                  PASTA_ARQUIVOS=str(RAIZ / "data" / "teste_arquivos"))

from app import protheus  # noqa: E402
from app.models import Nota, Status  # noqa: E402


def _nota(**kw) -> Nota:
    base = dict(id=7, status=Status.APROVADA, empresa="AXT", filial="2", fornecedor="10DS6V", numero="54321",
                serie="", tipo_doc="NF", valor=1500.5, produto="S_1.07", cc="1810", conta_contabil="30110010030",
                vencimento=date(2026, 11, 20), emissao=date(2026, 11, 1), cnpj_emitente="53113791000122",
                prestador="TOTVS", descricao="Licença", pc="", chave_acesso="", criado_em=datetime(2026, 11, 2),
                protheus_doc="", protheus_erro="")
    base.update(kw)
    return Nota(**base)


def test_payload_documento_de_entrada():
    p = protheus.montar_payload(_nota())
    assert (p["rotina"], p["empresa"], p["filial"], p["fornecedor"], p["loja"]) == ("MATA103", "02", "02", "10DS6V", "01")
    assert (p["documento"], p["serie"], p["especie"], p["emissao"]) == ("000054321", "1", "NFS", "20261101")
    it = p["itens"][0]
    assert (it["produto"], it["valorTotal"], it["tes"], it["centroCusto"], it["contaContabil"]) == \
        ("S_1.07", 1500.5, "001", "1810", "30110010030")
    assert p["idExterno"] == "CNOTAS-7"


def test_payload_fatura_loja_e_numero_longo():
    p = protheus.montar_payload(_nota(tipo_doc="FT", fornecedor="01ona7/02", numero="NFS-202600000123456"))
    assert (p["fornecedor"], p["loja"], p["especie"], p["serie"]) == ("01ONA7", "02", "FAT", "FT")
    assert p["documento"] == "000123456"  # F1_DOC tem 9 posições: ficam os últimos dígitos


def test_payload_valida_campos_e_empresa():
    with pytest.raises(protheus.ErroProtheus, match="fornecedor.*CC"):
        protheus.montar_payload(_nota(fornecedor="", cc=""))
    with pytest.raises(protheus.ErroProtheus, match="sem grupo"):
        protheus.montar_payload(_nota(empresa="XPTO"))


def test_interpretar_respostas():
    r = protheus.interpretar_resposta(200, json.dumps(
        {"sucesso": True, "documento": "000054321", "serie": "1", "recno": 99, "pedidoCompra": "004790"}))
    assert (r.documento, r.recno, r.pedido, r.ja_existia) == ("000054321", 99, "004790", False)
    with pytest.raises(protheus.ErroProtheus, match="TES 001 bloqueada"):
        protheus.interpretar_resposta(422, json.dumps(
            {"sucesso": False, "mensagem": "ExecAuto MATA103 recusou", "detalhe": "TES 001 bloqueada"}))
    with pytest.raises(protheus.ErroProtheus, match="HTTP 500"):
        protheus.interpretar_resposta(500, "Internal error")


def test_cliente_rest_envia_tenant_e_basic_auth(monkeypatch):
    vistos = []

    def responder(req: httpx.Request) -> httpx.Response:
        vistos.append(req)
        corpo = json.loads(req.content)
        return httpx.Response(200, json={"sucesso": True, "documento": corpo["documento"], "serie": corpo["serie"],
                                         "recno": 1, "jaExistia": False})

    c = protheus.ClienteProtheus.__new__(protheus.ClienteProtheus)
    c.base, c.endpoint, c.auth, c.usuario, c.senha, c._token = "http://erp/rest", "/centralnotas/v1/documento-entrada", \
        "basic", "integra", "s3nha", None
    c._http = httpx.Client(transport=httpx.MockTransport(responder))
    r = c.enviar(protheus.montar_payload(_nota()))
    assert r.documento == "000054321"
    req = vistos[0]
    assert str(req.url) == "http://erp/rest/centralnotas/v1/documento-entrada"
    assert req.headers["tenantId"] == "02,02" and req.headers["Authorization"].startswith("Basic ")


def test_lancar_atualiza_status_e_registra_erro(monkeypatch):
    class Falha:
        def enviar(self, payload):
            raise protheus.ErroProtheus("Fornecedor 10DS6V/01 não encontrado na SA2")

    class Ok:
        def enviar(self, payload):
            return protheus.Retorno(payload["documento"], payload["serie"], 5, "004790")

    eventos = []
    monkeypatch.setattr(protheus, "registrar", lambda db, n, acao, det="", quem="": eventos.append(acao))
    n = _nota()
    monkeypatch.setattr(protheus, "cliente", lambda: Falha())
    with pytest.raises(protheus.ErroProtheus):
        protheus.lancar(None, n)
    assert n.status == Status.APROVADA and "SA2" in n.protheus_erro

    monkeypatch.setattr(protheus, "cliente", lambda: Ok())
    protheus.lancar(None, n)
    assert (n.status, n.status_nota, n.pc, n.protheus_erro) == (Status.LANCADA, "NF LANÇADA", "004790", "")
    assert n.protheus_doc == "000054321/1 (recno 5)"
    assert eventos == ["Erro no lançamento Protheus", "Lançada no Protheus"]
    with pytest.raises(protheus.ErroProtheus, match="aprovadas"):
        protheus.lancar(None, n)
