"""Planilha de controle (.xlsx) no mesmo layout das abas mensais usadas pelo administrativo."""
from __future__ import annotations

import io
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select

from .config import settings
from .models import Nota, SessionLocal, Status

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
         "Setembro", "Outubro", "Novembro", "Dezembro"]

# Exatamente as 17 colunas das abas "Julho 26", "Agosto 26", ...
COLUNAS = [
    ("DESPESA", "despesa", 10), ("EMPRESA", "empresa", 10), ("PRESTADOR", "prestador", 18),
    ("DESCRIÇÃO", "descricao", 60), ("FILIAL", "filial", 8), ("PRODUTO", "produto", 12), ("CC ", "cc", 8),
    ("CONTA CONTABIL ", "conta_contabil", 15), ("FORNECEDOR", "fornecedor", 12), ("VALOR", "valor", 14),
    ("PC", "pc", 10), ("NFS", "numero", 12), ("CHAMADO", "chamado", 12), ("STATUS CHAMADO", "status_chamado", 24),
    ("STATUS NOTA", "status_nota", 30), ("DATA CHAMADO", "data_chamado", 13), ("VENCIMENTO", "vencimento", 13),
]
CONTROLE = [
    ("ID APP", "id", 8), ("ABA", None, 14), ("ETAPA NO APP", "status", 22), ("PRESTADOR", "prestador", 18),
    ("NFS", "numero", 12), ("RAZÃO SOCIAL", "razao_social", 40), ("CNPJ", "cnpj_emitente", 16),
    ("APROVADO POR", "aprovado_por", 28), ("DATA DECISÃO", "decisao_em", 16), ("DOC. PROTHEUS", "protheus_doc", 22),
    ("PASTA DOS ARQUIVOS", "pasta", 50),
]


def nome_aba(nota: Nota) -> str:
    d = nota.criado_em
    return f"{MESES[d.month - 1]} {d:%y}"


def _valor(nota: Nota, attr: str):
    v = getattr(nota, attr)
    if attr == "valor" and v is not None:
        return float(v)
    if attr in ("filial", "cc", "conta_contabil", "numero") and isinstance(v, str) and v.isdigit() and not v.startswith("0"):
        return int(v)  # igual à planilha atual (números, não texto)
    return v


def _cabecalho(ws, colunas, cor):
    ws.append([c[0] for c in colunas])
    for i, (_, _, larg) in enumerate(colunas, 1):
        cel = ws.cell(row=1, column=i)
        cel.font, cel.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor=cor)
        cel.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = larg
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}1"


def gerar() -> bytes:
    with SessionLocal() as db:
        notas = db.scalars(select(Nota).where(Nota.status != Status.IGNORADA).order_by(Nota.criado_em, Nota.id)).all()
    por_aba: dict[str, list[Nota]] = defaultdict(list)
    for n in notas:
        por_aba[nome_aba(n)].append(n)

    wb = Workbook()
    wb.remove(wb.active)
    for aba, lista in por_aba.items():
        ws = wb.create_sheet(aba)
        _cabecalho(ws, COLUNAS, "1F3864")
        for n in lista:
            ws.append([_valor(n, a) for _, a, _ in COLUNAS])
        for row in ws.iter_rows(min_row=2):
            row[9].number_format = '"R$" #,##0.00'
            row[15].number_format = row[16].number_format = "DD/MM/YYYY"

    ws = wb.create_sheet("Controle app")
    _cabecalho(ws, CONTROLE, "7F7F7F")
    for n in notas:
        ws.append([nome_aba(n) if a is None else _valor(n, a) for _, a, _ in CONTROLE])
    for row in ws.iter_rows(min_row=2):
        row[8].number_format = "DD/MM/YYYY HH:MM"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def atualizar_arquivo() -> None:
    """Cópia sempre atualizada na pasta de arquivos (para quem prefere abrir no Excel)."""
    destino = settings().pasta_arquivos / "CONTROLE_NOTAS.xlsx"
    try:
        destino.write_bytes(gerar())
    except PermissionError:  # arquivo aberto no Excel por alguém
        (settings().pasta_arquivos / "CONTROLE_NOTAS (atualização pendente).xlsx").write_bytes(gerar())
