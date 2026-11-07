"""Gera e-mails de exemplo em data/demo para testar o app sem credenciais (MODO_DEMO=true).

    python scripts/gerar_demo.py
"""
import json
import shutil
from datetime import date
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

RAIZ = Path(__file__).resolve().parent.parent
DEMO = RAIZ / "data" / "demo"
ANEXOS = DEMO / "anexos"


def pdf(nome: str, linhas: list[str]) -> str:
    c = canvas.Canvas(str(ANEXOS / nome), pagesize=A4)
    y = 800
    for l in linhas:
        c.setFont("Helvetica-Bold" if l.isupper() else "Helvetica", 11)
        c.drawString(50, y, l)
        y -= 18
    c.save()
    return nome


def linha_digitavel(valor: float, venc: date) -> str:
    fator = 1000 + (venc - date(2025, 2, 22)).days
    campo5 = f"{fator:04d}{int(round(valor * 100)):010d}"
    return f"00190.00009 01234.567891 23456.789012 3 {campo5}"


def email(id_, remetente, assunto, corpo, anexos, recebido="2026-11-05T09:00:00Z"):
    (DEMO / f"{id_}.json").write_text(json.dumps({
        "id": id_, "remetente": remetente, "assunto": assunto, "corpo": corpo,
        "anexos": anexos, "recebido_em": recebido}, ensure_ascii=False, indent=2), encoding="utf-8")


NFE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00"><NFe><infNFe Id="NFe35261153113791000122550010000543211000543210" versao="4.00">
<ide><serie>1</serie><nNF>54321</nNF><dhEmi>2026-11-03T10:15:00-03:00</dhEmi></ide>
<emit><CNPJ>53113791000122</CNPJ><xNome>TOTVS S.A.</xNome><xFant>TOTVS</xFant></emit>
<dest><CNPJ>03987645000310</CNPJ><xNome>AXT</xNome></dest>
<det nItem="1"><prod><xProd>SUPORTE PRIME MONITOR ENTERPRISE - TOTVS CRM - NOV/2026</xProd></prod></det>
<total><ICMSTot><vNF>12500.00</vNF></ICMSTot></total>
<cobr><dup><nDup>001</nDup><dVenc>2026-11-20</dVenc><vDup>12500.00</vDup></dup></cobr>
</infNFe></NFe></nfeProc>"""


def main():
    shutil.rmtree(DEMO, ignore_errors=True)
    ANEXOS.mkdir(parents=True)

    # 1) TOTVS: XML + DANFE + boleto no mesmo e-mail
    (ANEXOS / "NFe35261153113791000122550010000543211000543210.xml").write_text(NFE_XML, encoding="utf-8")
    pdf("DANFE_54321.pdf", ["DANFE", "Documento Auxiliar da Nota Fiscal Eletronica", "TOTVS S.A.  CNPJ 53.113.791/0001-22",
                            "Nota Fiscal No 000.054.321  Serie 1", "Valor Total da Nota R$ 12.500,00"])
    pdf("Boleto_54321.pdf", ["RECIBO DO PAGADOR", "Beneficiario: TOTVS S.A. CNPJ 53.113.791/0001-22",
                             "Referente NF 54321", "Vencimento 20/11/2026", "Valor do Documento R$ 12.500,00",
                             linha_digitavel(12500.00, date(2026, 11, 20))])
    email("demo-1", "faturamento@totvs.com.br", "NF 54321 - Manutenção Protheus - Novembro",
          "Prezados, segue NF e boleto referente à manutenção de novembro.",
          ["NFe35261153113791000122550010000543211000543210.xml", "DANFE_54321.pdf", "Boleto_54321.pdf"])

    # 2) VIVO: fatura em PDF (com linha digitável), sem XML
    pdf("Fatura_Vivo_Nov26.pdf", ["FATURA DE SERVICOS DE TELECOMUNICACOES", "Telefonica Brasil S.A. CNPJ 02.558.157/0001-62",
                                  "Cliente: VMT CNPJ 05.828.732/0001-98", "No da Fatura: 123654879",
                                  "Emissao 01/11/2026", "Total a pagar R$ 3.489,90", "Vencimento 15/11/2026",
                                  linha_digitavel(3489.90, date(2026, 11, 15))])
    email("demo-2", "fatura@vivo.com.br", "Sua fatura Vivo Empresas chegou",
          "Olá! Sua fatura de novembro está disponível em anexo.", ["Fatura_Vivo_Nov26.pdf"], "2026-11-05T09:30:00Z")

    # 3) Fornecedor NOVO (sem cadastro): NFS-e PDF + memória de cálculo + boleto, tomador LUNA
    pdf("NFSe_120.pdf", ["NFS-E - NOTA FISCAL DE SERVICO ELETRONICA", "Numero da Nota: 120",
                         "Prestador: NOVATECH CONSULTORIA LTDA CNPJ 11.222.333/0001-81",
                         "Tomador: LUNA CNPJ 64.817.850/0001-60", "Emissao 04/11/2026",
                         "Discriminacao: Consultoria em processos - outubro/2026", "Valor Liquido da Nota R$ 8.000,00"])
    pdf("Memoria de calculo outubro.pdf", ["MEMORIA DE CALCULO", "Ref. NFS-e 120", "160 horas x R$ 50,00 = R$ 8.000,00"])
    pdf("Boleto Novatech.pdf", ["FICHA DE COMPENSACAO", "Beneficiario: NOVATECH CONSULTORIA LTDA", "Nosso numero 120",
                                "Vencimento 06/11/2026", linha_digitavel(8000.00, date(2026, 11, 6))])
    email("demo-3", "financeiro@novatech.com.br", "NF 120 - Consultoria outubro",
          "Bom dia! Segue nota, memória de cálculo e boleto.",
          ["NFSe_120.pdf", "Memoria de calculo outubro.pdf", "Boleto Novatech.pdf"], "2026-11-05T10:00:00Z")

    # 5) ERPWORKS: projeto (histórico indica CAPEX / 141104 / ZERDG2 na VMT)
    pdf("NFSe_920_ERPWORKS.pdf", ["NFS-E - NOTA FISCAL DE SERVICO ELETRONICA", "Numero da Nota: 920",
                                  "Prestador: TMSIGA SISTEMAS LTDA CNPJ 53.260.240/0001-91",
                                  "Tomador: VMT CNPJ 05.828.732/0065-52", "Emissao 03/11/2026",
                                  "Discriminacao: DESENV. SISTEMAS - Projeto Implementacao do PDV Quiosque - Competencia Outubro/2026 - 24 hrs",
                                  "Valor Liquido da Nota R$ 3.299,04", "Vencimento 05/12/2026"])
    email("demo-5", "faturamento@erpworks.com.br", "NFS-e 920 - Outubro", "Segue NFS-e.",
          ["NFSe_920_ERPWORKS.pdf"], "2026-11-05T10:15:00Z")

    # 4) E-mail que não é nota
    email("demo-4", "newsletter@fornecedor.com", "Novidades de novembro", "Confira nossas promoções!", [],
          "2026-11-05T10:30:00Z")
    print(f"Demo gerada em {DEMO}")


if __name__ == "__main__":
    main()
