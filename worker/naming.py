"""Nomenclatura padrão do administrativo e organização em pastas.

NF / FT  = PRESTADOR_NFouFT_NUMERO_EMPRESA            ex.: TOTVS_NF_54321_AXT
BOLETO   = PRESTADOR_NFouFT_NUMERO_EMPRESA_BOLETO     ex.: TOTVS_NF_54321_AXT_BOLETO
MEMÓRIA  = PRESTADOR_NFouFT_NUMERO_EMPRESA_MC         ex.: BEFORE_NF_120_LUNA_MC
XML      = mesmo nome da NF, extensão .xml
"""
from __future__ import annotations

import re
import unicodedata

SUFIXO = {"BOLETO": "_BOLETO", "MC": "_MC", "OUTRO": "_ANEXO"}


def limpar(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().upper().strip()
    txt = re.sub(r"[^A-Z0-9]+", "-", txt).strip("-")
    return txt


def apelido_sugerido(fantasia: str, razao: str) -> str:
    """'TELEFONICA BRASIL S.A.' -> 'TELEFONICA'. O analista pode corrigir; o app memoriza."""
    base = fantasia or razao
    palavras = [p for p in limpar(base).split("-") if p not in {"SA", "S", "A", "LTDA", "ME", "EPP", "EIRELI", "CIA", "DE", "DO", "DA"}]
    return palavras[0] if palavras else ""


def nome_base(prestador: str, tipo_doc: str, numero: str, empresa: str) -> str:
    partes = [limpar(prestador) or "SEMPRESTADOR", tipo_doc if tipo_doc in ("NF", "FT") else "NF",
              limpar(numero) or "SEMNUMERO", limpar(empresa) or "SEMEMPRESA"]
    return "_".join(partes)


def nome_documento(base: str, tipo: str, extensao: str) -> str:
    return f"{base}{SUFIXO.get(tipo, '')}{extensao.lower()}"
