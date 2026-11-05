"""Envio do pedido de aprovação e registro da decisão (por botão no e-mail ou por resposta)."""
from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime
from html import escape
from pathlib import Path

from .config import regras_aprovacao, settings
from .models import Email, Nota, Status, registrar

TAG_ASSUNTO = "NOTA #{id}"
_RE_TAG = re.compile(r"\[NOTA #(\d+)\]", re.I)


def id_nota_no_assunto(assunto: str) -> int | None:
    m = _RE_TAG.search(assunto or "")
    return int(m.group(1)) if m else None


def escolher_aprovadores(nota: Nota) -> tuple[str, list[str]]:
    for r in regras_aprovacao().get("regras", []):
        v = float(nota.valor or 0)
        if "valor_min" in r and v < r["valor_min"]:
            continue
        if "valor_max" in r and v > r["valor_max"]:
            continue
        if "cc" in r and str(r["cc"]).upper() != (nota.cc or "").upper():
            continue
        if "prestador" in r and str(r["prestador"]).upper() != (nota.prestador or "").upper():
            continue
        if "empresa" in r and str(r["empresa"]).upper() != (nota.empresa or "").upper():
            continue
        return r.get("nome", ""), list(r["aprovadores"])
    return "", []


def assinatura(nota_id: int, email: str) -> str:
    msg = f"{nota_id}:{email.lower()}".encode()
    return hmac.new(settings().segredo_app.encode(), msg, hashlib.sha256).hexdigest()[:32]


def link(nota_id: int, email: str) -> str:
    return f"{settings().url_base}/aprovacao/{nota_id}?e={email}&s={assinatura(nota_id, email)}"


def assinatura_valida(nota_id: int, email: str, sig: str) -> bool:
    return hmac.compare_digest(assinatura(nota_id, email), sig or "")


def _brl(v) -> str:
    return "—" if v is None else f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def montar_html(nota: Nota, aprovador: str) -> str:
    linhas = [
        ("Prestador", f"{nota.prestador} ({nota.razao_social})" if nota.razao_social else nota.prestador),
        ("NFS", f"{nota.tipo_doc} {nota.numero}"), ("Empresa / Filial", f"{nota.empresa} / {nota.filial}"),
        ("Despesa", nota.despesa), ("Descrição", nota.descricao), ("Produto", nota.produto),
        ("CC", nota.cc), ("Conta contábil", nota.conta_contabil), ("Fornecedor (Protheus)", nota.fornecedor),
        ("Valor", _brl(nota.valor)),
        ("Vencimento", nota.vencimento.strftime("%d/%m/%Y") if nota.vencimento else "—"),
    ]
    tabela = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{escape(k)}</td><td style='padding:4px 0'><b>{escape(str(v or '—'))}</b></td></tr>"
        for k, v in linhas)
    url = link(nota.id, aprovador)
    botao = ("display:inline-block;padding:10px 22px;border-radius:6px;color:#fff;"
             "text-decoration:none;font-weight:bold;margin-right:8px;")
    return f"""<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#222">
<p>Olá,</p><p>Solicito o seu <b>de acordo</b> para lançamento da nota abaixo (arquivos em anexo).</p>
<table style="border-collapse:collapse">{tabela}</table>
<p style="margin:22px 0">
<a href="{escape(url + '&acao=aprovar')}" style="{botao}background:#1a7f37">De acordo</a>
<a href="{escape(url + '&acao=reprovar')}" style="{botao}background:#b42318">Não de acordo</a></p>
<p style="color:#666;font-size:12px">Você também pode simplesmente <b>responder este e-mail</b> com
"De acordo" (ou "Não de acordo – motivo"). Mantenha <b>[NOTA #{nota.id}]</b> no assunto.</p></div>"""


def enviar_pedido(db, nota: Nota, quem: str, cliente_graph) -> list[str]:
    regra, aprovadores = escolher_aprovadores(nota)
    if not aprovadores:
        raise ValueError("Nenhuma regra de aprovação encontrada — confira config/aprovacao.yaml")
    anexos = []
    for d in nota.documentos:
        p = Path(d.caminho)
        if p.exists() and d.tipo != "XML":
            anexos.append((d.nome_final or d.nome_original, p.read_bytes(), d.content_type or "application/pdf"))
    # Mantém o status do chamado alinhado à planilha
    nota.status_chamado = nota.status_chamado or "SUSPENSO - APROV"
    assunto = f"[NOTA #{nota.id}] De acordo para lançamento – {nota.prestador} {nota.tipo_doc} {nota.numero} {nota.empresa} – {_brl(nota.valor)}"
    for ap in aprovadores:  # um e-mail por aprovador para que cada um tenha seu link assinado
        cliente_graph.enviar_email([ap], assunto, montar_html(nota, ap), anexos)
    nota.status = Status.AGUARDANDO
    nota.aprovadores = ";".join(aprovadores)
    nota.aprovado_por, nota.decisao_em, nota.comentario_aprovacao = "", None, ""
    registrar(db, nota, "Enviada para aprovação", f"Regra '{regra}': {', '.join(aprovadores)}", quem)
    return aprovadores


def registrar_decisao(db, nota: Nota, aprovador: str, aprovado: bool, comentario: str, via: str) -> bool:
    if nota.status != Status.AGUARDANDO:
        return False
    nota.status = Status.APROVADA if aprovado else Status.REPROVADA
    nota.aprovado_por, nota.decisao_em, nota.comentario_aprovacao = aprovador, datetime.now(), comentario
    registrar(db, nota, "Aprovada" if aprovado else "Reprovada", f"via {via}. {comentario}".strip(), aprovador)
    return True


def interpretar_resposta(corpo: str) -> bool | None:
    """Lê só o começo da resposta (antes do histórico citado)."""
    topo = re.split(r"\n\s*(De:|From:|Enviado:|Sent:|-----|________________)", corpo or "", maxsplit=1)[0]
    topo = topo.lower()[:400]
    cfg = regras_aprovacao()
    if any(re.search(rf"\b{re.escape(p)}\b", topo) for p in cfg.get("palavras_reprovado", [])):
        return False
    if any(re.search(rf"\b{re.escape(p)}\b", topo) for p in cfg.get("palavras_aprovado", [])):
        return True
    return None


def processar_resposta(db, nota_id: int, remetente: str, corpo: str, email: Email) -> None:
    nota = db.get(Nota, nota_id)
    if not nota:
        return
    autorizados = [a.lower() for a in (nota.aprovadores or "").split(";") if a]
    if remetente.lower() not in autorizados:
        registrar(db, nota, "Resposta ignorada", f"{remetente} não é aprovador desta nota")
        return
    decisao = interpretar_resposta(corpo)
    if decisao is None:
        registrar(db, nota, "Resposta sem decisão", f"{remetente}: {email.preview[:200]}")
        return
    registrar_decisao(db, nota, remetente, decisao, email.preview[:300], "resposta de e-mail")
