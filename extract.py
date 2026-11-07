"""Extração de dados de NF-e (XML), NFS-e (XML – padrão Nacional e ABRASF), PDFs e boletos."""
from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from lxml import etree

import os

log = logging.getLogger(__name__)


@dataclass
class Dados:
    tipo_doc: str = ""          # NF | FT
    numero: str = ""
    serie: str = ""
    chave_acesso: str = ""
    cnpj_emitente: str = ""
    razao_emitente: str = ""
    fantasia_emitente: str = ""
    cnpj_tomador: str = ""
    emissao: date | None = None
    valor: float | None = None
    vencimento: date | None = None
    descricao: str = ""
    linha_digitavel: str = ""
    origem: str = ""
    cnpjs_encontrados: list[str] = field(default_factory=list)
    razoes: dict = field(default_factory=dict)  # CNPJ -> nome lido no PDF

    def mesclar(self, outro: "Dados") -> "Dados":
        """Preenche campos vazios com os do outro (o atual tem prioridade)."""
        for k, v in asdict(outro).items():
            if k == "cnpjs_encontrados":
                self.cnpjs_encontrados = list(dict.fromkeys(self.cnpjs_encontrados + v))
            elif k == "razoes":
                self.razoes = {**v, **self.razoes}
            elif v not in (None, "", []) and getattr(self, k) in (None, "", []):
                setattr(self, k, v)
        return self


def so_digitos(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def _num(v: str | None) -> float | None:
    if not v:
        return None
    v = v.strip()
    if "," in v:  # formato BR 1.234,56
        v = v.replace(".", "").replace(",", ".")
    try:
        return round(float(v), 2)
    except ValueError:
        return None


def _data(v: str | None) -> date | None:
    if not v:
        return None
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(v[:10] if fmt == "%Y-%m-%d" else v, fmt).date()
        except ValueError:
            continue
    return None


# ======================================================================= XML
def _busca(raiz, *caminhos: str) -> str:
    """Busca o primeiro texto encontrado em caminhos de local-names (ignora namespaces).
    Ex.: 'emit/CNPJ' -> //*[local-name()='emit']/*[local-name()='CNPJ']"""
    for c in caminhos:
        xp = "//" + "/".join(f"*[local-name()='{p}']" for p in c.split("/"))
        r = raiz.xpath(xp)
        if r and (r[0].text or "").strip():
            return r[0].text.strip()
    return ""


def extrair_xml(conteudo: bytes) -> Dados | None:
    try:
        raiz = etree.fromstring(conteudo, parser=etree.XMLParser(recover=True, resolve_entities=False))
    except etree.XMLSyntaxError:
        return None
    if raiz is None:
        return None

    # ---- NF-e (produto) ----
    if raiz.xpath("//*[local-name()='infNFe']"):
        inf = raiz.xpath("//*[local-name()='infNFe']")[0]
        d = Dados(tipo_doc="NF", origem="xml")
        d.chave_acesso = so_digitos(inf.get("Id", ""))
        d.numero = _busca(raiz, "ide/nNF").lstrip("0")
        d.serie = _busca(raiz, "ide/serie")
        d.emissao = _data(_busca(raiz, "ide/dhEmi", "ide/dEmi"))
        d.cnpj_emitente = _busca(raiz, "emit/CNPJ")
        d.razao_emitente = _busca(raiz, "emit/xNome")
        d.fantasia_emitente = _busca(raiz, "emit/xFant")
        d.cnpj_tomador = _busca(raiz, "dest/CNPJ")
        d.valor = _num(_busca(raiz, "total/ICMSTot/vNF"))
        d.vencimento = _data(_busca(raiz, "cobr/dup/dVenc"))
        itens = [e.text for e in raiz.xpath("//*[local-name()='det']/*[local-name()='prod']/*[local-name()='xProd']")][:3]
        d.descricao = "; ".join(i.strip() for i in itens if i)
        return d

    # ---- NFS-e padrão Nacional (obrigatório desde 2026) ----
    if raiz.xpath("//*[local-name()='infNFSe']"):
        d = Dados(tipo_doc="NF", origem="xml")
        d.numero = _busca(raiz, "infNFSe/nNFSe").lstrip("0")
        d.chave_acesso = so_digitos(raiz.xpath("//*[local-name()='infNFSe']")[0].get("Id", ""))
        d.emissao = _data(_busca(raiz, "infNFSe/dhProc", "infDPS/dhEmi"))
        d.cnpj_emitente = _busca(raiz, "infNFSe/emit/CNPJ", "infDPS/prest/CNPJ")
        d.razao_emitente = _busca(raiz, "infNFSe/emit/xNome")
        d.fantasia_emitente = _busca(raiz, "infNFSe/emit/xFant")
        d.cnpj_tomador = _busca(raiz, "infDPS/toma/CNPJ")
        d.valor = _num(_busca(raiz, "infNFSe/valores/vLiq", "valores/vServPrest/vServ"))
        d.descricao = _busca(raiz, "cServ/xDescServ")[:300]
        return d

    # ---- NFS-e ABRASF (municipais) ----
    if raiz.xpath("//*[local-name()='InfNfse' or local-name()='CompNfse' or local-name()='Nfse']"):
        d = Dados(tipo_doc="NF", origem="xml")
        d.numero = _busca(raiz, "InfNfse/Numero", "Nfse/Numero", "Numero").lstrip("0")
        d.chave_acesso = _busca(raiz, "CodigoVerificacao")
        d.emissao = _data(_busca(raiz, "DataEmissao"))
        d.cnpj_emitente = _busca(raiz, "PrestadorServico/IdentificacaoPrestador/Cnpj",
                                 "Prestador/CpfCnpj/Cnpj", "PrestadorServico/IdentificacaoPrestador/CpfCnpj/Cnpj",
                                 "IdentificacaoPrestador/Cnpj")
        d.razao_emitente = _busca(raiz, "PrestadorServico/RazaoSocial")
        d.fantasia_emitente = _busca(raiz, "PrestadorServico/NomeFantasia")
        d.cnpj_tomador = _busca(raiz, "TomadorServico/IdentificacaoTomador/CpfCnpj/Cnpj",
                                "Tomador/IdentificacaoTomador/CpfCnpj/Cnpj")
        d.valor = _num(_busca(raiz, "ValorLiquidoNfse", "ValorServicos"))
        d.descricao = _busca(raiz, "Discriminacao")[:300]
        return d
    return None


# ======================================================================= BOLETO
_BASE_FATOR_1 = date(1997, 10, 7)
_BASE_FATOR_2 = date(2025, 2, 22)  # fator reiniciou em 1000 nesta data


def decodificar_linha_digitavel(texto: str, hoje: date | None = None) -> tuple[str, float | None, date | None]:
    """Procura a linha digitável no texto e devolve (linha, valor, vencimento)."""
    hoje = hoje or date.today()
    padroes = [
        r"\d{5}[.\s]?\d{5}\s+\d{5}[.\s]?\d{6}\s+\d{5}[.\s]?\d{6}\s+\d\s+\d{14}",  # bancário formatado
        r"(?<!\d)\d{47}(?!\d)",
        r"8\d{10}[\s-]?\d\s+\d{11}[\s-]?\d\s+\d{11}[\s-]?\d\s+\d{11}[\s-]?\d",  # concessionária
        r"(?<!\d)8\d{47}(?!\d)",
    ]
    for p in padroes:
        m = re.search(p, texto)
        if not m:
            continue
        lin = so_digitos(m.group(0))
        if len(lin) == 47:
            fator, valor = int(lin[33:37]), int(lin[37:47]) / 100
            venc = None
            if fator >= 1000:
                cands = [_BASE_FATOR_1 + timedelta(days=fator), _BASE_FATOR_2 + timedelta(days=fator - 1000)]
                venc = min(cands, key=lambda d: abs((d - hoje).days))
            return lin, (valor or None), venc
        if len(lin) == 48:  # concessionária: remove DVs de cada bloco de 12
            cod = "".join(lin[i:i + 11] for i in range(0, 48, 12))
            return lin, (int(cod[4:15]) / 100 or None), None
    return "", None, None


# ======================================================================= PDF
def texto_pdf(conteudo: bytes, max_paginas: int = 5) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages[:max_paginas])
    except Exception as e:  # PDF protegido, imagem escaneada etc.
        log.warning("Falha ao ler PDF: %s", e)
        return ""


_RE_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
_RE_DATA = r"(\d{2}/\d{2}/\d{4})"
_RE_VALOR = r"R?\$?\s*([\d.]+,\d{2})"


def extrair_texto(texto: str, tipo: str) -> Dados:
    """Heurísticas por expressão regular sobre o texto do PDF."""
    d = Dados(origem="pdf")
    t = re.sub(r"[ \t]+", " ", texto)
    d.cnpjs_encontrados = list(dict.fromkeys(so_digitos(c) for c in _RE_CNPJ.findall(t)))

    if tipo == "BOLETO":
        d.linha_digitavel, d.valor, d.vencimento = decodificar_linha_digitavel(t)

    if not d.vencimento:
        m = re.search(r"vencimento\D{0,25}" + _RE_DATA, t, re.I)
        d.vencimento = _data(m.group(1)) if m else None
    if not d.valor:
        for rot in (r"valor\s+(?:total\s+)?(?:l[ií]quido\s+)?da\s+nota", r"valor\s+total\s+a\s+pagar",
                    r"total\s+a\s+pagar", r"valor\s+do\s+documento", r"valor\s+total", r"valor\s+cobrado"):
            m = re.search(rot + r"\D{0,30}?" + _RE_VALOR, t, re.I)
            if m:
                d.valor = _num(m.group(1))
                break
    for rot in (r"n[úu]mero\s+da\s+(?:nota|nfs-?e)", r"nfs-?e\s*n[ºo°.]*", r"nota\s+fiscal\s*n[ºo°.]*",
                r"fatura\s*n[ºo°.]*", r"n[ºo°]\.?\s*(?:da\s+fatura|do\s+documento)", r"\bn[ºo°]\.?"):
        m = re.search(rot + r"\s*:?\s*([0-9][0-9./-]{0,20})", t, re.I)
        if m:
            d.numero = so_digitos(m.group(1)).lstrip("0") or m.group(1)
            break
    m = re.search(r"(?:discrimina[çc][ãa]o(?:\s+dos\s+servi[çc]os)?|descri[çc][ãa]o\s+do\s+servi[çc]o)\s*:?\s*([^\n]{5,200})", texto, re.I)
    d.descricao = m.group(1).strip() if m else ""
    m = re.search(r"emiss[ãa]o\D{0,25}" + _RE_DATA, t, re.I)
    d.emissao = _data(m.group(1)) if m else None
    m = re.search(r"\b(\d{4}\s?){11}\b", t)  # chave de acesso de 44 dígitos impressa no DANFE
    if m and len(so_digitos(m.group(0))) == 44:
        d.chave_acesso = so_digitos(m.group(0))
    if d.cnpjs_encontrados:
        d.cnpj_emitente = d.cnpjs_encontrados[0]
    # nome que aparece na mesma linha do CNPJ (ex.: "Prestador: BEFORE CONSULTORIA LTDA CNPJ ...")
    for linha in texto.splitlines():
        m = _RE_CNPJ.search(linha)
        if not m:
            continue
        nome = re.sub(r"(?i)\b(cnpj|cpf/cnpj|cnpj/cpf)\b\s*:?\s*$", "", linha[:m.start()]).strip(" -:|")
        nome = re.sub(r"(?i)^(prestador|tomador|benefici[aá]rio|cedente|emitente|cliente|raz[aã]o social)"
                      r"(\s+de\s+servi[cç]os?)?\s*:?\s*", "", nome).strip(" -:|")
        if len(nome) >= 3:
            d.razoes.setdefault(so_digitos(m.group(0)), nome[:200])
    return d


def extrair_com_ia(conteudo_pdf: bytes, tipo: str) -> Dados | None:
    """Usa o Claude para ler o PDF quando as heurísticas não bastam (opcional)."""
    chave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not chave:
        return None
    try:
        import base64

        import anthropic
        cli = anthropic.Anthropic(api_key=chave)
        prompt = (
            f"Este PDF é um documento do tipo {tipo} (NF=nota fiscal, FT=fatura, BOLETO, MC=memória de cálculo) "
            "recebido pelo financeiro de uma empresa brasileira. Extraia e responda SOMENTE um JSON com as chaves: "
            "numero, serie, chave_acesso, cnpj_emitente, razao_emitente, fantasia_emitente, cnpj_tomador, "
            "emissao (AAAA-MM-DD), valor (número, total a pagar), vencimento (AAAA-MM-DD), descricao (até 150 caracteres). "
            "Use null quando não encontrar. CNPJs só com dígitos."
        )
        r = cli.messages.create(
            model=os.environ.get("MODELO_IA", "claude-sonnet-4-5"), max_tokens=800,
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                "data": base64.b64encode(conteudo_pdf).decode()}},
                {"type": "text", "text": prompt},
            ]}],
        )
        bruto = r.content[0].text
        j = json.loads(bruto[bruto.find("{"): bruto.rfind("}") + 1])
        d = Dados(origem="ia")
        for k in ("numero", "serie", "chave_acesso", "razao_emitente", "fantasia_emitente", "descricao"):
            setattr(d, k, str(j.get(k) or ""))
        d.cnpj_emitente, d.cnpj_tomador = so_digitos(j.get("cnpj_emitente")), so_digitos(j.get("cnpj_tomador"))
        d.numero = so_digitos(d.numero).lstrip("0") or d.numero
        d.emissao, d.vencimento = _data(j.get("emissao")), _data(j.get("vencimento"))
        d.valor = float(j["valor"]) if j.get("valor") is not None else None
        return d
    except Exception as e:
        log.warning("Extração por IA falhou: %s", e)
        return None
