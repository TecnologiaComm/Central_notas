"""Classifica cada anexo: NF, FT, XML, BOLETO, MC ou OUTRO (pelo nome e, se preciso, pelo conteúdo)."""
from __future__ import annotations

import re
import unicodedata

from .models import TipoDoc

EXT_IGNORADAS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ics", ".vcf", ".p7s", ".htm", ".html"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s)


def deve_ignorar(nome: str, inline: bool, tamanho: int) -> bool:
    ext = ("." + nome.rsplit(".", 1)[-1].lower()) if "." in nome else ""
    if inline or ext in EXT_IGNORADAS:
        return True  # logos de assinatura, convites de calendário etc.
    return ext not in {".pdf", ".xml"}


def classificar(nome: str, texto_pdf: str = "") -> TipoDoc:
    n = f" {_norm(nome)} "
    if nome.lower().endswith(".xml"):
        return TipoDoc.XML
    if re.search(r" (boleto|bol|bloqueto|2 via|segunda via) ", n):
        return TipoDoc.BOLETO
    if re.search(r" (mc|memoria|calculo|medicao|demonstrativo|relatorio) ", n):
        return TipoDoc.MC
    if re.search(r" (ft|fatura|fat) ", n):
        return TipoDoc.FT
    if re.search(r" (nf|nfe|nfs|nfse|nota|danfe|danfse) ", n):
        return TipoDoc.NF

    t = _norm(texto_pdf[:4000])
    if re.search(r"linha digitavel|nosso numero|ficha de compensacao|recibo do pagador|beneficiario", t) \
            or re.search(r"\d{5}\.\d{5} \d{5}\.\d{6} \d{5}\.\d{6} \d \d{14}", texto_pdf):
        return TipoDoc.BOLETO
    if re.search(r"memoria de calculo|medicao", t):
        return TipoDoc.MC
    if re.search(r"danfe|nota fiscal|nfs e|nfse|documento auxiliar da", t):
        return TipoDoc.NF
    if re.search(r"\bfatura\b|conta de consumo|nota fiscal fatura", t):
        return TipoDoc.FT
    return TipoDoc.OUTRO
