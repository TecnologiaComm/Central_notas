"""FASE 2 — Integração com o Protheus: lançamento da nota aprovada via REST.

Lado Protheus: o endpoint customizado em `protheus/CENTRALNOTAS.tlpp` (compilar no RPO e publicar no
AppServer REST) recebe o JSON montado aqui e chama o MATA103 (Documento de Entrada) — ou o MATA140
(pré-nota), conforme `config/protheus.yaml` — via MsExecAuto.

Lado app:
- botão "Lançar no Protheus" na nota aprovada (ou lançamento automático com PROTHEUS_LANCAR_AUTOMATICO=true);
- grava documento/série/recno retornados, preenche PC e status e tira a nota da fila;
- idempotente: o endpoint procura antes o documento (fornecedor+loja+doc+série) e devolve o existente;
- em erro, a mensagem do ExecAuto fica na nota (e o automático não tenta de novo até alguém reenviar).

Em MODO_DEMO (sem PROTHEUS_URL), um simulador grava o JSON em data/demo_protheus/ e devolve um número fictício.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx
from sqlalchemy import func, select

from .config import RAIZ, protheus_cfg, settings
from .models import Nota, SessionLocal, Status, registrar

log = logging.getLogger(__name__)


class ErroProtheus(Exception):
    """Erro de validação ou retornado pelo Protheus (mensagem pronta para mostrar ao analista)."""


@dataclass
class Retorno:
    documento: str
    serie: str
    recno: int | None = None
    pedido: str = ""
    ja_existia: bool = False
    mensagem: str = ""


# ------------------------------------------------------------------ montagem do payload
def _cfg_empresa(empresa: str) -> dict:
    cfg = protheus_cfg()
    padrao = dict(cfg.get("padrao") or {})
    especifico = (cfg.get("empresas") or {}).get((empresa or "").upper())
    if especifico is None:
        raise ErroProtheus(f"Empresa '{empresa or '?'}' sem grupo do Protheus em config/protheus.yaml")
    return {**padrao, **especifico}


def _so_digitos(v) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def _data_protheus(d: date | None) -> str:
    return d.strftime("%Y%m%d") if d else ""


def rotina() -> str:
    return str(protheus_cfg().get("rotina") or "MATA103").upper()


def documento_protheus(numero: str) -> str:
    """F1_DOC: só dígitos, com zeros à esquerda; se maior que o campo, mantém os últimos dígitos."""
    tam = int(protheus_cfg().get("tamanho_documento") or 9)
    dig = _so_digitos(numero)
    return dig[-tam:].zfill(tam) if dig else ""


def fornecedor_loja(codigo: str, loja_padrao: str) -> tuple[str, str]:
    """'10DS6V' -> ('10DS6V', '01');  '10DS6V/02' ou '10DS6V-02' -> ('10DS6V', '02')."""
    codigo = (codigo or "").strip().upper()
    for sep in ("/", "-"):
        if sep in codigo:
            c, loja = codigo.split(sep, 1)
            return c.strip(), loja.strip()
    return codigo, loja_padrao


def validar(nota: Nota) -> list[str]:
    faltando = [rot for rot, v in (
        ("empresa", nota.empresa), ("filial", nota.filial), ("fornecedor (código Protheus)", nota.fornecedor),
        ("NFS", _so_digitos(nota.numero)), ("valor", nota.valor), ("produto", nota.produto),
        ("CC", nota.cc), ("conta contábil", nota.conta_contabil), ("vencimento", nota.vencimento),
    ) if not v]
    return [f"Falta {', '.join(faltando)}"] if faltando else []


def montar_payload(nota: Nota) -> dict:
    erros = validar(nota)
    if erros:
        raise ErroProtheus("; ".join(erros))
    e = _cfg_empresa(nota.empresa)
    ft = (nota.tipo_doc or "NF").upper() == "FT"
    cod, loja = fornecedor_loja(nota.fornecedor, str(e.get("loja") or "01"))
    valor = round(float(nota.valor), 2)
    emissao = nota.emissao or (nota.criado_em.date() if nota.criado_em else date.today())
    filial = str(nota.filial).zfill(int(protheus_cfg().get("tamanho_filial") or 2))
    return {
        "idExterno": f"CNOTAS-{nota.id}",
        "rotina": rotina(),
        "empresa": str(e["grupo"]),
        "filial": filial,
        "fornecedor": cod,
        "loja": loja,
        "cnpjFornecedor": nota.cnpj_emitente,
        "documento": documento_protheus(nota.numero),
        "serie": (nota.serie or e.get("serie_ft" if ft else "serie_nf") or "").upper()[:3],
        "especie": e.get("especie_ft" if ft else "especie_nf") or "NFS",
        "emissao": _data_protheus(emissao),
        "chaveAcesso": nota.chave_acesso or "",
        "condicaoPagamento": str(e.get("condicao_pagamento") or ""),
        "natureza": str(e.get("natureza") or ""),
        "vencimento": _data_protheus(nota.vencimento),
        "valorTotal": valor,
        "pedidoCompra": nota.pc or "",
        "historico": f"{nota.prestador} {nota.tipo_doc} {nota.numero} - {nota.descricao}".strip()[:250],
        "itens": [{
            "item": "0001",
            "produto": nota.produto,
            "quantidade": 1,
            "valorUnitario": valor,
            "valorTotal": valor,
            "tes": str(e.get("tes") or ""),
            "centroCusto": nota.cc,
            "contaContabil": nota.conta_contabil,
            "pedidoCompra": nota.pc or "",
        }],
    }


# ------------------------------------------------------------------ clientes
class ClienteProtheus:
    def __init__(self) -> None:
        s = settings()
        self.base = s.protheus_url.rstrip("/")
        self.endpoint = s.protheus_endpoint
        self.auth = s.protheus_auth.lower()
        self.usuario, self.senha = s.protheus_usuario, s.protheus_senha
        self._http = httpx.Client(timeout=s.protheus_timeout_s, verify=s.protheus_verificar_tls)
        self._token: tuple[str, datetime] | None = None

    def _cabecalhos(self, empresa: str, filial: str) -> dict:
        h = {"Content-Type": "application/json", "tenantId": f"{empresa},{filial}"}
        if self.auth == "oauth2":
            h["Authorization"] = f"Bearer {self._bearer()}"
        return h

    def _bearer(self) -> str:
        if self._token and self._token[1] > datetime.now():
            return self._token[0]
        r = self._http.post(f"{self.base}/api/oauth2/v1/token", params={
            "grant_type": "password", "username": self.usuario, "password": self.senha})
        if r.status_code >= 400:
            raise ErroProtheus(f"Falha ao autenticar no Protheus (HTTP {r.status_code})")
        d = r.json()
        validade = max(int(d.get("expires_in", 3600)) - 60, 60)
        self._token = (d["access_token"], datetime.fromtimestamp(datetime.now().timestamp() + validade))
        return self._token[0]

    def enviar(self, payload: dict) -> Retorno:
        kw = {"auth": (self.usuario, self.senha)} if self.auth == "basic" else {}
        try:
            r = self._http.post(f"{self.base}{self.endpoint}", json=payload,
                                headers=self._cabecalhos(payload["empresa"], payload["filial"]), **kw)
        except httpx.HTTPError as e:
            raise ErroProtheus(f"Protheus indisponível: {e}") from e
        return interpretar_resposta(r.status_code, r.text)


class ProtheusDemo:
    """Simulador para MODO_DEMO: guarda o JSON enviado e devolve um documento fictício."""

    def __init__(self) -> None:
        self.pasta = RAIZ / "data" / "demo_protheus"
        self.lancados: dict[str, dict] = {}

    def enviar(self, payload: dict) -> Retorno:
        self.pasta.mkdir(parents=True, exist_ok=True)
        (self.pasta / f"{payload['idExterno']}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        chave = f"{payload['empresa']}{payload['filial']}{payload['fornecedor']}{payload['loja']}" \
                f"{payload['documento']}{payload['serie']}"
        ja = chave in self.lancados
        d = self.lancados.setdefault(chave, {"recno": 1000 + len(self.lancados),
                                             "pedido": payload["pedidoCompra"] or f"D{len(self.lancados):05d}"})
        return Retorno(payload["documento"], payload["serie"], d["recno"], d["pedido"], ja, "Simulado (MODO_DEMO)")


def interpretar_resposta(status_http: int, corpo: str) -> Retorno:
    try:
        d = json.loads(corpo or "{}")
    except ValueError:
        d = {}
    if status_http >= 400 or d.get("sucesso") is False:
        msg = d.get("mensagem") or d.get("message") or d.get("errorMessage") or (corpo or "")[:500]
        detalhe = d.get("detalhe") or d.get("detailedMessage") or ""
        raise ErroProtheus(f"Protheus recusou (HTTP {status_http}): {msg}" + (f" — {detalhe}" if detalhe else ""))
    if not d.get("documento"):
        raise ErroProtheus(f"Resposta inesperada do Protheus: {(corpo or '')[:300]}")
    recno = d.get("recno")
    return Retorno(str(d["documento"]), str(d.get("serie", "")), int(recno) if recno else None,
                   str(d.get("pedidoCompra") or ""), bool(d.get("jaExistia")), str(d.get("mensagem") or ""))


_cliente = None


def habilitado() -> bool:
    s = settings()
    return bool(s.protheus_url) or s.modo_demo


def cliente():
    global _cliente
    if _cliente is None:
        s = settings()
        if s.protheus_url:
            _cliente = ClienteProtheus()
        elif s.modo_demo:
            _cliente = ProtheusDemo()
        else:
            raise ErroProtheus("Integração com o Protheus não configurada (PROTHEUS_URL no .env)")
    return _cliente


# ------------------------------------------------------------------ lançamento
def lancar(db, nota: Nota, quem: str = "sistema") -> Retorno:
    """Lança a nota aprovada no Protheus e atualiza PC/status. Em erro, registra e relança ErroProtheus."""
    if nota.status != Status.APROVADA:
        raise ErroProtheus(f"Só notas aprovadas vão para o Protheus (etapa atual: {nota.status})")
    if nota.protheus_doc:
        raise ErroProtheus(f"Nota já lançada no Protheus: {nota.protheus_doc}")
    try:
        payload = montar_payload(nota)
        ret = cliente().enviar(payload)
    except ErroProtheus as e:
        nota.protheus_erro = str(e)
        registrar(db, nota, "Erro no lançamento Protheus", str(e), quem)
        raise
    nota.protheus_erro = ""
    nota.protheus_doc = f"{ret.documento}/{ret.serie}" + (f" (recno {ret.recno})" if ret.recno else "")
    if ret.pedido and not nota.pc:
        nota.pc = ret.pedido
    if payload["rotina"] == "MATA140":
        nota.status_nota = "AGUARDANDO LANÇAMENTO FISCAL"
    else:
        nota.status_nota = "NF LANÇADA"
        nota.status = Status.LANCADA
    if len(_so_digitos(nota.numero)) > len(payload["documento"]):
        registrar(db, nota, "Número ajustado para o Protheus", f"{nota.numero} → {payload['documento']}", quem)
    registrar(db, nota, "Lançada no Protheus",
              f"{payload['rotina']} · doc {nota.protheus_doc} · empresa {payload['empresa']} filial {payload['filial']}"
              + (" · já existia no Protheus" if ret.ja_existia else "") + (f" · PC {nota.pc}" if nota.pc else ""),
              quem)
    return ret


def lancar_pendentes() -> dict:
    """Lançamento automático: notas aprovadas, ainda sem documento e sem erro pendente."""
    s = settings()
    if not s.protheus_lancar_automatico or not habilitado():
        return {"lancadas": 0, "erros": 0}
    ok = erros = 0
    with SessionLocal() as db:
        ids = db.scalars(select(Nota.id).where(Nota.status == Status.APROVADA, func.coalesce(Nota.protheus_doc, "") == "",
                                               func.coalesce(Nota.protheus_erro, "") == "")).all()
        for nota_id in ids:
            nota = db.get(Nota, nota_id)
            try:
                lancar(db, nota, "lançamento automático")
                ok += 1
            except ErroProtheus as e:
                log.warning("Nota #%s não lançada no Protheus: %s", nota_id, e)
                erros += 1
            db.commit()
    return {"lancadas": ok, "erros": erros}
