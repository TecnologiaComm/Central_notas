"""Sugere DESPESA / PRODUTO / CC / CONTA CONTÁBIL / FORNECEDOR / FILIAL a partir do histórico.

Regra: entre as linhas já lançadas do mesmo PRESTADOR (de preferência na mesma EMPRESA),
escolhe a de DESCRIÇÃO mais parecida com a da nota nova; empate -> a mais recente.
Ex.: ERPWORKS/VMT "Projeto ..." costuma ser CAPEX 141104, "Banco de horas" é OPEX 413337.
"""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select

from .models import Historico

_IGNORAR = {"de", "da", "do", "das", "dos", "e", "a", "o", "em", "para", "ref", "competencia", "comp", "hrs", "hr",
            "horas", "parc", "parcela", "mensal", "janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
            "agosto", "setembro", "outubro", "novembro", "dezembro", "jan", "fev", "mar", "abr", "mai", "jun", "jul",
            "ago", "set", "out", "nov", "dez"}


def _tokens(txt: str) -> set[str]:
    t = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().lower()
    return {p for p in re.findall(r"[a-z][a-z0-9]{2,}", t) if p not in _IGNORAR}


def _similaridade(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def sugerir(db, prestador: str, empresa: str, descricao: str = "", fornecedor: str = "") -> tuple[dict, str]:
    """Retorna (campos sugeridos, explicação)."""
    if not prestador:
        return {}, ""
    linhas = db.scalars(select(Historico).where(Historico.prestador == prestador.upper())
                        .order_by(Historico.data_ref.desc(), Historico.id.desc())).all()
    if not linhas:
        return {}, ""
    mesma_empresa = [h for h in linhas if empresa and h.empresa == empresa.upper()]
    candidatas = mesma_empresa or linhas
    if fornecedor:  # mesmo prestador pode ter CNPJs/códigos diferentes (ex.: VIVO 01ONA7 x ZERB2X)
        candidatas = [h for h in candidatas if h.fornecedor == fornecedor] or candidatas
    alvo = _tokens(descricao)
    melhor = max(enumerate(candidatas),
                 key=lambda ih: (_similaridade(alvo, _tokens(ih[1].descricao)), -ih[0]))[1]
    campos = {k: getattr(melhor, k) for k in ("despesa", "produto", "cc", "conta_contabil", "fornecedor", "filial")
              if getattr(melhor, k)}
    if not mesma_empresa:
        campos.pop("fornecedor", None)  # código do fornecedor muda por empresa
        campos.pop("filial", None)
    campos["descricao_modelo"] = melhor.descricao
    quando = melhor.data_ref.strftime("%m/%Y") if melhor.data_ref else "?"
    explicacao = (f"Sugestão baseada em {prestador}/{melhor.empresa} de {quando}: “{melhor.descricao[:90]}”"
                  + ("" if mesma_empresa else " (outra empresa — confira CC/conta)"))
    return campos, explicacao


def opcoes(db, campo: str) -> list[str]:
    """Valores já usados (para listas de seleção na tela)."""
    col = getattr(Historico, campo)
    return [v for v in db.scalars(select(col).distinct().order_by(col)) if v]
