"""Fluxo completo em modo demo: e-mail -> nota -> conferência -> aprovação (botão e resposta) -> planilha."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
os.environ.update(MODO_DEMO="true", URL_BASE="http://testserver", SEGREDO_APP="teste",
                  DATABASE_URL=f"sqlite:///{RAIZ / 'data' / 'teste.db'}",
                  PASTA_ARQUIVOS=str(RAIZ / "data" / "teste_arquivos"))


def test_fluxo_completo():
    (RAIZ / "data" / "teste.db").unlink(missing_ok=True)
    shutil.rmtree(RAIZ / "data" / "teste_arquivos", ignore_errors=True)
    shutil.rmtree(RAIZ / "data" / "demo_enviados", ignore_errors=True)
    subprocess.run([sys.executable, str(RAIZ / "scripts" / "gerar_demo.py")], check=True)

    from fastapi.testclient import TestClient
    from openpyxl import load_workbook

    from app.main import app
    from app.models import Fornecedor, Nota, SessionLocal, Status

    with TestClient(app) as c:
        assert c.post("/verificar", follow_redirects=False).status_code == 303
        assert c.get("/").status_code == 200

        with SessionLocal() as db:
            q = {n.prestador: n for n in db.query(Nota).all()}
        # Empresa/filial pelo CNPJ do tomador; código do fornecedor e classificação pelo histórico
        t = q["TOTVS"]
        assert (t.empresa, t.filial, t.fornecedor, t.cc, t.conta_contabil) == ("AXT", "2", "10DS6V", "1810", "30110010030")
        v = q["VIVO"]
        assert (v.empresa, v.filial, v.fornecedor, v.tipo_doc) == ("VMT", "1", "01ONA7", "FT")
        e = q["ERPWORKS"]
        assert (e.empresa, e.filial, e.despesa, e.conta_contabil, e.fornecedor) == ("VMT", "99", "CAPEX", "141104", "ZERDG2")
        novo = q["NOVATECH"]
        assert novo.empresa == "LUNA" and any("sem cadastro" in a for a in novo.lista_alertas)

        # Fornecedor novo: analista completa e pede o "de acordo"
        form = dict(despesa="OPEX", empresa="LUNA", filial="1", prestador="NOVATECH", descricao="Consultoria outubro",
                    produto="S_1.07", cc="9915", conta_contabil="413337", fornecedor="ZNOVA1", valor="8.000,00",
                    numero="120", tipo_doc="NF", vencimento="2026-11-06", razao_social="NOVATECH CONSULTORIA LTDA",
                    cnpj_emitente="11222333000181", acao="enviar")
        c.post(f"/nota/{novo.id}", data=form, follow_redirects=False)
        with SessionLocal() as db:
            n = db.get(Nota, novo.id)
            nomes = sorted(d.nome_final for d in n.documentos)
            assert n.status == Status.AGUARDANDO and n.status_chamado == "SUSPENSO - APROV"
            assert db.get(Fornecedor, "11222333000181").codigo("LUNA") == "ZNOVA1"
        assert nomes == ["NOVATECH_NF_120_LUNA.pdf", "NOVATECH_NF_120_LUNA_BOLETO.pdf", "NOVATECH_NF_120_LUNA_MC.pdf"]

        # Robson clica no link (GET só mostra a confirmação; POST registra)
        enviado = sorted((RAIZ / "data" / "demo_enviados").glob("*.html"))[-1].read_text()
        assert "rbastos@commcenter.com.br" in enviado
        url = re.search(r'href="(http://testserver/aprovacao/[^"]+)&amp;acao=aprovar"', enviado).group(1).replace("&amp;", "&")
        assert c.get(url).status_code == 200
        with SessionLocal() as db:
            assert db.get(Nota, novo.id).status == Status.AGUARDANDO
        em = re.search(r"e=([^&]+)", url).group(1)
        sig = re.search(r"s=([^&]+)", url).group(1)
        c.post(f"/aprovacao/{novo.id}", data={"e": em, "s": sig, "acao": "aprovar"})
        with SessionLocal() as db:
            assert db.get(Nota, novo.id).status == Status.APROVADA

        # TOTVS: Robson responde "De acordo" ao e-mail
        c.post(f"/nota/{t.id}", data={"acao": "enviar"})
        (RAIZ / "data" / "demo" / "resp.json").write_text(json.dumps({
            "id": "resp-1", "remetente": "rbastos@commcenter.com.br",
            "assunto": f"RE: [NOTA #{t.id}] De acordo para lançamento", "corpo": "De acordo.\n\nDe: Prestação de Contas TI\n...",
            "anexos": [], "recebido_em": "2026-11-05T12:00:00Z"}))
        c.post("/verificar")
        with SessionLocal() as db:
            n = db.get(Nota, t.id)
            assert n.status == Status.APROVADA and n.aprovado_por == "rbastos@commcenter.com.br"

        # Lançamento: PC + chamado; "NF LANÇADA" fecha a nota
        c.post(f"/nota/{t.id}", data={"acao": "lancamento", "pc": "004790", "chamado": "3182700",
                                       "status_chamado": "ENCERRADO", "status_nota": "NF LANÇADA",
                                       "data_chamado": "2026-11-05"})
        with SessionLocal() as db:
            assert db.get(Nota, t.id).status == Status.LANCADA

        # Planilha no layout das abas mensais
        wb = load_workbook(filename=__import__("io").BytesIO(c.get("/planilha.xlsx").content))
        assert wb.sheetnames == ["Novembro 26", "Controle app"]
        ws = wb["Novembro 26"]
        assert [x.value for x in ws[1]] == ["DESPESA", "EMPRESA", "PRESTADOR", "DESCRIÇÃO", "FILIAL", "PRODUTO", "CC ",
                                            "CONTA CONTABIL ", "FORNECEDOR", "VALOR", "PC", "NFS", "CHAMADO",
                                            "STATUS CHAMADO", "STATUS NOTA", "DATA CHAMADO", "VENCIMENTO"]
        assert ws.max_row == 5
