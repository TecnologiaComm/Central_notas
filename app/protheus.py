"""FASE 2 — Integração com o Protheus (ainda não implementada).

Caminho sugerido, a validar com a TI/consultoria TOTVS:
1. Expor no Protheus um endpoint REST (TLPP/ADVPL) que receba os dados da nota aprovada e chame
   o MATA103 (Documento de Entrada) via MsExecAuto — ou a pré-nota (MATA140) se o processo
   exigir classificação fiscal manual.
2. Este módulo envia o JSON da nota (fornecedor/loja, filial, número, série, emissão, valor,
   natureza/CC/conta, vencimento) e grava o número/recno retornado na nota.
3. Status da nota passa para "Lançada no Protheus" automaticamente.

Até lá, o analista lança manualmente e clica em "Marcar como lançada" no app.
"""
from __future__ import annotations

from .models import Nota


def montar_payload(nota: Nota) -> dict:
    return {
        "filial": nota.filial, "cnpj_fornecedor": nota.cnpj_emitente, "documento": nota.numero,
        "serie": nota.serie, "emissao": nota.emissao.isoformat() if nota.emissao else None,
        "valor": float(nota.valor or 0), "cc": nota.cc, "conta_contabil": nota.conta_contabil,
        "produto": nota.produto, "vencimento": nota.vencimento.isoformat() if nota.vencimento else None,
        "historico": nota.descricao,
    }


def lancar(nota: Nota) -> str:
    raise NotImplementedError("Integração com o Protheus prevista para a fase 2")
