"""Ações do analista: salvar conferência, renomear/organizar arquivos e alimentar o histórico."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import select

from .extract import so_digitos
from .ingest import calcular_alertas
from .models import Fornecedor, Historico, Nota, Status, registrar
from .naming import mover_sem_sobrescrever, nome_base, nome_documento, pasta_da_nota

CAMPOS_TEXTO = ("tipo_doc", "numero", "despesa", "empresa", "prestador", "razao_social", "descricao", "filial",
                "produto", "cc", "conta_contabil", "fornecedor", "pc", "chamado", "status_chamado", "status_nota")
MAIUSCULAS = {"tipo_doc", "despesa", "empresa", "prestador", "produto", "fornecedor"}


def _data(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


def aplicar_formulario(nota: Nota, form: dict) -> None:
    for c in CAMPOS_TEXTO:
        if c in form:
            v = (form[c] or "").strip()
            setattr(nota, c, v.upper() if c in MAIUSCULAS else v)
    if "cnpj_emitente" in form:
        nota.cnpj_emitente = so_digitos(form["cnpj_emitente"])
    if "valor" in form:
        v = (form["valor"] or "").replace("R$", "").strip()
        if "," in v:
            v = v.replace(".", "").replace(",", ".")
        nota.valor = round(float(v), 2) if v else None
    for c in ("vencimento", "data_chamado"):
        if c in form:
            setattr(nota, c, _data(form[c]))


def organizar_arquivos(nota: Nota) -> None:
    """Renomeia (PRESTADOR_NFouFT_NÚMERO_EMPRESA[_BOLETO|_MC]) e move para <EMPRESA>/<AAAA-MM>/."""
    base = nome_base(nota.prestador, nota.tipo_doc, nota.numero, nota.empresa)
    ref = nota.emissao or (nota.criado_em.date() if nota.criado_em else date.today())
    destino = pasta_da_nota(nota.empresa, f"{ref:%Y-%m}")
    contagem: dict[str, int] = {}
    for d in nota.documentos:
        p = Path(d.caminho)
        if not p.exists():
            continue
        tipo = {"XML": "NF", "NF": "NF", "FT": "NF"}.get(d.tipo, d.tipo)  # XML e PDF da nota sem sufixo
        nome = nome_documento(base, tipo, p.suffix)
        chave = f"{tipo}{p.suffix.lower()}"
        contagem[chave] = contagem.get(chave, 0) + 1
        if contagem[chave] > 1:
            nome = f"{Path(nome).stem}_{contagem[chave]}{p.suffix.lower()}"
        novo = mover_sem_sobrescrever(p, destino, nome)
        d.caminho, d.nome_final = str(novo), novo.name
    nota.pasta = str(destino)


def memorizar(db, nota: Nota) -> None:
    """Atualiza o cadastro do fornecedor e grava/atualiza a linha no histórico (melhora as próximas sugestões)."""
    if nota.cnpj_emitente and nota.prestador:
        f = db.get(Fornecedor, nota.cnpj_emitente) or Fornecedor(cnpj=nota.cnpj_emitente, apelido=nota.prestador)
        f.apelido, f.razao = nota.prestador, nota.razao_social or f.razao
        f.definir_codigo(nota.empresa, nota.fornecedor)
        db.merge(f)
    h = db.scalar(select(Historico).where(Historico.nota_id == nota.id)) or Historico(nota_id=nota.id, origem="app")
    h.data_ref = (nota.criado_em.date() if nota.criado_em else date.today()).replace(day=1)
    for k in ("despesa", "empresa", "prestador", "descricao", "filial", "produto", "cc",
              "conta_contabil", "fornecedor", "valor"):
        setattr(h, k, getattr(nota, k))
    h.nfs = nota.numero
    db.add(h)


def salvar(db, nota: Nota, form: dict, quem: str) -> None:
    aplicar_formulario(nota, form)
    organizar_arquivos(nota)
    memorizar(db, nota)
    db.flush()
    nota.alertas = "\n".join(calcular_alertas(db, nota))
    registrar(db, nota, "Conferência salva", f"Arquivos em {nota.pasta}", quem)


def salvar_lancamento(db, nota: Nota, form: dict, quem: str) -> None:
    """PC, chamado e status — preenchidos depois da aprovação."""
    aplicar_formulario(nota, {k: form[k] for k in ("pc", "chamado", "status_chamado", "status_nota", "data_chamado")
                              if k in form})
    if nota.status_nota == "NF LANÇADA" and nota.status == Status.APROVADA:
        nota.status = Status.LANCADA
    memorizar(db, nota)
    registrar(db, nota, "Lançamento atualizado",
              f"PC {nota.pc or '—'} · chamado {nota.chamado or '—'} · {nota.status_chamado or '—'} · {nota.status_nota or '—'}",
              quem)
