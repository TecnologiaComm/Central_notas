"""App web (FastAPI): fila de notas, conferência, aprovação e planilha.

Rodar:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select

from . import aprovacao, auth, conferencia, planilha, sharepoint, sugestao
from .auth import usuario
from .config import empresas, filiais, recarregar_config, settings
from .graph import cliente
from .ingest import verificar_caixa
from .models import (DESPESAS, STATUS_CHAMADO, STATUS_NOTA, Documento, Fornecedor, Historico, Nota, SessionLocal,
                     Status, iniciar_banco, registrar)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
BASE = Path(__file__).parent
_trava = threading.Lock()


def verificar_com_trava() -> dict:
    if not _trava.acquire(blocking=False):
        return {"ocupado": True}
    try:
        r = verificar_caixa()
        r["sharepoint"] = sharepoint.sincronizar_pendentes()  # só age com SHAREPOINT_SITE configurado
        planilha.atualizar_arquivo()
        sharepoint.enviar_planilha(planilha.gerar())
        return r
    finally:
        _trava.release()


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    iniciar_banco()
    agendador = BackgroundScheduler(timezone="America/Sao_Paulo")
    agendador.add_job(verificar_com_trava, "interval", minutes=settings().intervalo_verificacao_min,
                      id="caixa", max_instances=1, coalesce=True)
    agendador.start()
    yield
    agendador.shutdown(wait=False)


app = FastAPI(title="Central de Notas – Comm", lifespan=ciclo_de_vida)
app.middleware("http")(auth.exigir_login)
tpl = Jinja2Templates(directory=BASE / "templates")


def brl(v) -> str:
    return "—" if v is None else f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


tpl.env.filters["brl"] = brl
tpl.env.filters["data"] = lambda d: d.strftime("%d/%m/%Y") if d else "—"
tpl.env.filters["datahora"] = lambda d: d.strftime("%d/%m/%Y %H:%M") if d else "—"
tpl.env.globals.update(Status=Status, hoje=date.today, DESPESAS=DESPESAS, STATUS_CHAMADO=STATUS_CHAMADO,
                       STATUS_NOTA=STATUS_NOTA, login_obrigatorio=lambda: settings().login_obrigatorio,
                       sharepoint_habilitado=sharepoint.habilitado)

CLASSE_STATUS = {
    Status.CONFERENCIA: "amarelo", Status.AGUARDANDO: "azul", Status.APROVADA: "verde",
    Status.REPROVADA: "vermelho", Status.LANCADA: "cinza", Status.IGNORADA: "cinza",
}
tpl.env.globals["classe_status"] = lambda s: CLASSE_STATUS.get(s, "cinza")


@app.get("/saude")
def saude():
    """Verificação de saúde do Azure App Service (Health check path = /saude)."""
    with SessionLocal() as db:
        db.execute(select(1))
    return {"ok": True}


# ------------------------------------------------------------------ telas internas
@app.get("/", response_class=HTMLResponse)
def fila(request: Request, status: str = "", q: str = ""):
    with SessionLocal() as db:
        contagem = dict(db.execute(select(Nota.status, func.count()).group_by(Nota.status)).all())
        consulta = select(Nota).order_by(Nota.vencimento.is_(None), Nota.vencimento, Nota.id.desc())
        if status:
            consulta = consulta.where(Nota.status == status)
        else:
            consulta = consulta.where(Nota.status.notin_([Status.LANCADA, Status.IGNORADA]))
        if q:
            like = f"%{q}%"
            consulta = consulta.where(or_(Nota.fornecedor.ilike(like), Nota.numero.ilike(like), Nota.pc.ilike(like),
                                          Nota.prestador.ilike(like), Nota.empresa.ilike(like),
                                          Nota.chamado.ilike(like), Nota.descricao.ilike(like)))
        notas = db.scalars(consulta.limit(500)).all()
        return tpl.TemplateResponse(request, "fila.html", {
            "notas": notas, "contagem": contagem, "filtro": status, "q": q, "usuario": usuario(request)})


@app.post("/verificar")
def verificar_agora():
    r = verificar_com_trava()
    msg = "Verificação já em andamento" if r.get("ocupado") else \
        f"{r['notas']} nota(s), {r['respostas']} resposta(s) de aprovação, {r['ignorados']} e-mail(s) sem nota"
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("flash", msg, max_age=10)
    return resp


@app.get("/nota/{nota_id}", response_class=HTMLResponse)
def ver_nota(request: Request, nota_id: int):
    with SessionLocal() as db:
        nota = db.get(Nota, nota_id)
        if not nota:
            raise HTTPException(404)
        _ = nota.documentos, nota.eventos, nota.email
        regra, aprovadores = aprovacao.escolher_aprovadores(nota)
        abertas = db.scalars(select(Nota).where(
            Nota.id != nota.id, Nota.status.in_([Status.CONFERENCIA, Status.AGUARDANDO]))).all()
        return tpl.TemplateResponse(request, "nota.html", {
            "n": nota, "filiais": filiais(), "empresas": empresas(), "regra": regra, "aprovadores": aprovadores,
            "outras": abertas, "usuario": usuario(request),
            "opcoes": {c: sugestao.opcoes(db, c) for c in ("prestador", "produto", "cc", "conta_contabil")}})


@app.post("/nota/{nota_id}")
async def acao_nota(request: Request, nota_id: int):
    form = dict(await request.form())
    acao = form.pop("acao", "salvar")
    quem = usuario(request)
    flash = ""
    with SessionLocal() as db:
        nota = db.get(Nota, nota_id)
        if not nota:
            raise HTTPException(404)
        try:
            if acao in ("salvar", "enviar"):
                conferencia.salvar(db, nota, form, quem)
                flash = f"Salvo. Arquivos em {nota.pasta}"
                if acao == "enviar":
                    db.flush()
                    db.refresh(nota)
                    enviados = aprovacao.enviar_pedido(db, nota, quem, cliente())
                    flash = "Enviada para aprovação: " + ", ".join(enviados)
                    db.commit()
                    try:
                        sharepoint.sincronizar_nota(db, nota)
                    except Exception as e:  # não trava o fluxo: reenviado na próxima verificação
                        db.rollback()
                        flash += f" (SharePoint pendente: {e})"[:300]
            elif acao == "ignorar":
                nota.status = Status.IGNORADA
                registrar(db, nota, "Ignorada", form.get("motivo", ""), quem)
            elif acao == "reabrir":
                nota.status = Status.CONFERENCIA
                registrar(db, nota, "Reaberta para conferência", "", quem)
            elif acao == "lancamento":
                conferencia.salvar_lancamento(db, nota, form, quem)
                flash = "Dados de lançamento salvos"
            db.commit()
        except Exception as e:
            db.rollback()
            flash = f"Erro: {e}"
    planilha.atualizar_arquivo()
    resp = RedirectResponse(f"/nota/{nota_id}", status_code=303)
    resp.set_cookie("flash", flash, max_age=10)
    return resp


@app.post("/documento/{doc_id}/mover")
def mover_documento(request: Request, doc_id: int, destino: int = Form(...)):
    with SessionLocal() as db:
        doc = db.get(Documento, doc_id)
        origem = doc.nota_id
        alvo = db.get(Nota, destino)
        if not doc or not alvo:
            raise HTTPException(404)
        doc.nota_id = alvo.id
        registrar(db, alvo, "Documento vinculado", f"{doc.nome_original} veio da nota #{origem}", usuario(request))
        db.commit()
    return RedirectResponse(f"/nota/{destino}", status_code=303)


@app.get("/documento/{doc_id}")
def abrir_documento(doc_id: int):
    with SessionLocal() as db:
        doc = db.get(Documento, doc_id)
        if not doc or not Path(doc.caminho).exists():
            raise HTTPException(404)
        nome = doc.nome_final or doc.nome_original
        tipo = "application/pdf" if nome.lower().endswith(".pdf") else "application/xml"
        return FileResponse(doc.caminho, media_type=tipo, filename=nome,
                            content_disposition_type="inline")


@app.get("/planilha.xlsx")
def baixar_planilha():
    return Response(planilha.gerar(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="CONTROLE_NOTAS_{date.today():%Y-%m-%d}.xlsx"'})


@app.get("/fornecedores", response_class=HTMLResponse)
def fornecedores(request: Request):
    with SessionLocal() as db:
        lista = db.scalars(select(Fornecedor).order_by(Fornecedor.apelido)).all()
        _ = [f.mapa_codigos for f in lista]
        return tpl.TemplateResponse(request, "fornecedores.html", {"lista": lista, "usuario": usuario(request)})


@app.post("/usuario")
def definir_usuario(nome: str = Form(...)):
    if settings().login_obrigatorio:
        raise HTTPException(403, "Com login Microsoft, o usuário vem da conta logada")
    r = RedirectResponse("/", status_code=303)
    r.set_cookie("usuario", nome.strip()[:80], max_age=60 * 60 * 24 * 365)
    return r


@app.get("/carga", response_class=HTMLResponse)
def tela_carga(request: Request):
    with SessionLocal() as db:
        resumo = {"fornecedores": db.scalar(select(func.count()).select_from(Fornecedor)),
                  "historico": db.scalar(select(func.count()).select_from(Historico)),
                  "filiais": len(filiais())}
    return tpl.TemplateResponse(request, "carga.html", {"resumo": resumo, "usuario": usuario(request)})


@app.post("/carga")
def carregar_planilha(request: Request, arquivo: UploadFile = File(...)):
    """Importa a planilha atual (aba Infos + abas mensais) sem precisar de acesso ao servidor."""
    from .importacao import importar
    try:
        r = importar(arquivo.file, settings().pasta_dados / "config")
    except Exception as e:
        resp = RedirectResponse("/carga", status_code=303)
        resp.set_cookie("flash", f"Erro: planilha não reconhecida ({e})"[:300], max_age=10)
        return resp
    recarregar_config()
    with SessionLocal() as db:  # histórico vindo da planilha é substituído; o gerado pelo app é mantido
        db.query(Historico).filter(Historico.origem.like("planilha%")).delete(synchronize_session=False)
        db.commit()
    iniciar_banco()
    logging.getLogger(__name__).info("Carga da planilha por %s: %s", usuario(request), r)
    resp = RedirectResponse("/carga", status_code=303)
    resp.set_cookie("flash", f"Importado: {r['filiais']} filiais, {r['fornecedores']} fornecedores, "
                             f"{r['historico']} linhas de histórico", max_age=10)
    return resp


# ------------------------------------------------------------------ página do aprovador
@app.get("/aprovacao/{nota_id}", response_class=HTMLResponse)
def pagina_aprovacao(request: Request, nota_id: int, e: str, s: str, acao: str = "aprovar"):
    # GET só mostra a confirmação: o Safe Links do Outlook abre links automaticamente,
    # então a decisão só é registrada no POST (clique do aprovador).
    if not aprovacao.assinatura_valida(nota_id, e, s):
        raise HTTPException(403, "Link inválido")
    with SessionLocal() as db:
        nota = db.get(Nota, nota_id)
        _ = nota.documentos
        return tpl.TemplateResponse(request, "aprovacao.html", {
            "n": nota, "e": e, "s": s, "acao": acao, "concluido": None})


@app.post("/aprovacao/{nota_id}", response_class=HTMLResponse)
def decidir(request: Request, nota_id: int, e: str = Form(...), s: str = Form(...),
            acao: str = Form(...), comentario: str = Form("")):
    if not aprovacao.assinatura_valida(nota_id, e, s):
        raise HTTPException(403, "Link inválido")
    with SessionLocal() as db:
        nota = db.get(Nota, nota_id)
        logado = usuario(request) if settings().login_obrigatorio else ""
        via = "botão do e-mail" + (f" (logado como {logado})" if logado and logado != e.lower() else "")
        ok = aprovacao.registrar_decisao(db, nota, e, acao == "aprovar", comentario, via)
        db.commit()
        _ = nota.documentos
        resp = tpl.TemplateResponse(request, "aprovacao.html", {
            "n": nota, "e": e, "s": s, "acao": acao, "concluido": ok})
    planilha.atualizar_arquivo()
    return resp
