from datetime import date

from app.aprovacao import interpretar_resposta
from app.classify import classificar
from app.extract import decodificar_linha_digitavel, extrair_texto
from app.naming import apelido_sugerido, nome_base, nome_documento


def test_nomenclatura_exemplos_do_processo():
    assert nome_base("VIVO", "FT", "123654879", "VMT") == "VIVO_FT_123654879_VMT"
    b = nome_base("TOTVS", "NF", "54321", "AXT")
    assert nome_documento(b, "NF", ".pdf") == "TOTVS_NF_54321_AXT.pdf"
    assert nome_documento(b, "BOLETO", ".pdf") == "TOTVS_NF_54321_AXT_BOLETO.pdf"
    b = nome_base("Before", "NF", "120", "LUNA")
    assert nome_documento(b, "MC", ".PDF") == "BEFORE_NF_120_LUNA_MC.pdf"


def test_apelido():
    assert apelido_sugerido("", "TELEFÔNICA BRASIL S.A.") == "TELEFONICA"
    assert apelido_sugerido("TOTVS", "TOTVS S.A.") == "TOTVS"


def test_classificacao_por_nome_e_conteudo():
    assert classificar("Boleto_54321.pdf") == "BOLETO"
    assert classificar("Memoria de calculo outubro.pdf") == "MC"
    assert classificar("Fatura_Vivo.pdf") == "FT"
    assert classificar("DANFE_54321.pdf") == "NF"
    assert classificar("doc.pdf", "RECIBO DO PAGADOR ... Nosso Número") == "BOLETO"
    assert classificar("x.xml") == "XML"


def test_linha_digitavel_fator_novo():
    lin, valor, venc = decodificar_linha_digitavel(
        "00190.00009 01234.567891 23456.789012 3 16360001250000", hoje=date(2026, 11, 5))
    assert valor == 12500.00
    assert venc == date(2026, 11, 20)


def test_extracao_pdf_texto():
    d = extrair_texto("Numero da Nota: 120\nValor Liquido da Nota R$ 8.000,00\nVencimento 06/11/2026", "NF")
    assert (d.numero, d.valor, d.vencimento) == ("120", 8000.0, date(2026, 11, 6))


def test_resposta_aprovacao():
    assert interpretar_resposta("Aprovado.\n\nDe: Notas\nEnviado: ...") is True
    assert interpretar_resposta("De acordo.\n\nRobson") is True
    assert interpretar_resposta("Não de acordo, falta o PC\nDe: Notas") is False
    assert interpretar_resposta("Reprovado, valor errado\nDe: Notas") is False
    assert interpretar_resposta("Quem pediu esse serviço?\nDe: aprovado") is None
