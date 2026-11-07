"""Sugere DESPESA/PRODUTO/CC/CONTA/FORNECEDOR/FILIAL pela linha do histórico mais parecida."""
from __future__ import annotations

import re
import unicodedata

_IGNORAR = {"de", "da", "do", "das", "dos", "e", "a", "o", "em", "para", "ref", "competencia", "comp", "hrs", "hr",
            "horas", "parc", "parcela", "mensal", "janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
            "agosto", "setembro", "outubro", "novembro", "dezembro", "jan", "fev", "mar", "abr", "mai", "jun", "jul",
            "ago", "set", "out", "nov", "dez"}


def tokens(txt: str) -> set[str]:
    t = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().lower()
    return {p for p in re.findall(r"[a-z][a-z0-9]{2,}", t) if p not in _IGNORAR}


def _sim(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def sugerir(linhas: list[dict], prestador: str, empresa: str, descricao: str = "",
            fornecedor: str = "") -> tuple[dict, str]:
    """linhas = histórico do prestador, mais recente primeiro."""
    if not prestador or not linhas:
        return {}, ""
    mesma = [h for h in linhas if empresa and h.get("empresa") == empresa]
    cand = mesma or linhas
    if fornecedor:
        cand = [h for h in cand if h.get("fornecedor") == fornecedor] or cand
    alvo = tokens(descricao)
    melhor = max(enumerate(cand), key=lambda ih: (_sim(alvo, tokens(ih[1].get("descricao", ""))), -ih[0]))[1]
    campos = {k: melhor[k] for k in ("despesa", "produto", "cc", "conta_contabil", "fornecedor", "filial") if melhor.get(k)}
    if not mesma:
        campos.pop("fornecedor", None)
        campos.pop("filial", None)
    campos["descricao_modelo"] = melhor.get("descricao", "")
    quando = (melhor.get("data_ref") or "")[:7]
    exp = f"Sugestão baseada em {prestador}/{melhor.get('empresa')} de {quando}: “{(melhor.get('descricao') or '')[:90]}”"
    if not mesma:
        exp += " (outra empresa — confira CC/conta)"
    return campos, exp
