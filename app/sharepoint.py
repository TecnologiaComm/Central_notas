"""Cópia dos arquivos renomeados (e da planilha) numa biblioteca do SharePoint, via Microsoft Graph.

A pasta local (<PASTA_ARQUIVOS>) continua sendo a cópia de trabalho do app; o SharePoint recebe a mesma
estrutura <SHAREPOINT_PASTA>/<EMPRESA>/<AAAA-MM>/<arquivo> para o time consultar e buscar pelo Microsoft 365.

Permissão de aplicativo no Entra ID: Sites.Selected (com escrita concedida só ao site das notas)
— ou Sites.ReadWrite.All, se a TI preferir. Falhas aqui não travam a conferência: os arquivos pendentes
são reenviados na próxima verificação da caixa.
"""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

import httpx
from sqlalchemy import func, select

from .config import RAIZ, settings
from .models import Documento, Nota, SessionLocal, Status, registrar

log = logging.getLogger(__name__)
GRAPH = "https://graph.microsoft.com/v1.0"
LIMITE_PUT_SIMPLES = 4 * 1024 * 1024
BLOCO = 5 * 1024 * 1024  # múltiplo de 320 KiB, como o Graph exige


class ErroSharePoint(Exception):
    pass


def habilitado() -> bool:
    return bool(settings().sharepoint_site)


def _caminho_url(rel: str) -> str:
    return "/".join(quote(p) for p in rel.strip("/").split("/") if p)


class SharePoint:
    def __init__(self, token, http: httpx.Client | None = None) -> None:
        s = settings()
        self._token = token  # função que devolve um token do Graph (o mesmo app do Outlook)
        self._http = http or httpx.Client(timeout=120)
        self.site, self.biblioteca, self.raiz = s.sharepoint_site, s.sharepoint_biblioteca, s.sharepoint_pasta
        self._drive: str | None = None

    def _req(self, metodo: str, url: str, **kw) -> httpx.Response:
        url = url if url.startswith("http") else f"{GRAPH}{url}"
        h = {"Authorization": f"Bearer {self._token()}", **kw.pop("headers", {})}
        r = self._http.request(metodo, url, headers=h, **kw)
        if r.status_code >= 400:
            raise ErroSharePoint(f"SharePoint HTTP {r.status_code}: {r.text[:300]}")
        return r

    def drive_id(self) -> str:
        if not self._drive:
            site = self._req("GET", f"/sites/{self.site}").json()["id"]
            drives = self._req("GET", f"/sites/{site}/drives").json().get("value", [])
            achado = next((d for d in drives if d["name"].lower() == self.biblioteca.lower()), None)
            if not achado:
                nomes = ", ".join(d["name"] for d in drives)
                raise ErroSharePoint(f"Biblioteca '{self.biblioteca}' não encontrada no site (existem: {nomes})")
            self._drive = achado["id"]
        return self._drive

    def _item(self, rel: str) -> str:
        return f"/drives/{self.drive_id()}/root:/{_caminho_url(f'{self.raiz}/{rel}')}"

    def enviar(self, rel: str, conteudo: bytes) -> dict:
        """Grava (substituindo) <raiz>/<rel>. Devolve {id, webUrl}."""
        if len(conteudo) <= LIMITE_PUT_SIMPLES:
            d = self._req("PUT", f"{self._item(rel)}:/content", content=conteudo,
                          params={"@microsoft.graph.conflictBehavior": "replace"}).json()
        else:
            sessao = self._req("POST", f"{self._item(rel)}:/createUploadSession",
                               json={"item": {"@microsoft.graph.conflictBehavior": "replace"}}).json()["uploadUrl"]
            total, d = len(conteudo), {}
            for ini in range(0, total, BLOCO):
                parte = conteudo[ini:ini + BLOCO]
                r = self._http.put(sessao, content=parte, headers={  # URL pré-autenticada: sem Authorization
                    "Content-Range": f"bytes {ini}-{ini + len(parte) - 1}/{total}"})
                if r.status_code >= 400:
                    raise ErroSharePoint(f"Upload em partes falhou: HTTP {r.status_code}")
                d = r.json() if r.content else d
        return {"id": d.get("id", ""), "webUrl": d.get("webUrl", "")}

    def excluir(self, item_id: str) -> None:
        try:
            self._req("DELETE", f"/drives/{self.drive_id()}/items/{item_id}")
        except ErroSharePoint as e:
            if "HTTP 404" not in str(e):
                raise

    def url_pasta(self, rel: str) -> str:
        return self._req("GET", self._item(rel)).json().get("webUrl", "")


class SharePointDemo:
    """MODO_DEMO: copia para data/demo_sharepoint, imitando a biblioteca."""

    def __init__(self) -> None:
        self.pasta = RAIZ / "data" / "demo_sharepoint" / settings().sharepoint_pasta

    def enviar(self, rel: str, conteudo: bytes) -> dict:
        destino = self.pasta / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)
        return {"id": rel, "webUrl": destino.as_uri()}

    def excluir(self, item_id: str) -> None:
        (self.pasta / item_id).unlink(missing_ok=True)

    def url_pasta(self, rel: str) -> str:
        return (self.pasta / rel).as_uri()


_cliente = None


def cliente():
    global _cliente
    if _cliente is None:
        if settings().modo_demo:
            _cliente = SharePointDemo()
        else:
            from .graph import cliente as graph
            _cliente = SharePoint(graph()._token)
    return _cliente


# ------------------------------------------------------------------ sincronização
def _relativo(caminho: str) -> str | None:
    try:
        return Path(caminho).resolve().relative_to(settings().pasta_arquivos).as_posix()
    except ValueError:
        return None


def pendentes(nota: Nota) -> list[Documento]:
    return [d for d in nota.documentos if d.nome_final and d.sharepoint_nome != d.nome_final]


def sincronizar_nota(db, nota: Nota) -> int:
    """Envia os arquivos já renomeados que ainda não estão (com o nome atual) no SharePoint."""
    if not habilitado():
        return 0
    sp, enviados, pasta_rel = cliente(), 0, None
    for d in pendentes(nota):
        rel = _relativo(d.caminho)
        if not rel or not Path(d.caminho).exists():
            continue
        if d.sharepoint_id:  # renomeado/movido depois do último envio: remove a versão antiga
            sp.excluir(d.sharepoint_id)
        r = sp.enviar(rel, Path(d.caminho).read_bytes())
        d.sharepoint_id, d.sharepoint_url, d.sharepoint_nome = r["id"], r["webUrl"], d.nome_final
        pasta_rel = rel.rsplit("/", 1)[0]
        enviados += 1
    if pasta_rel:
        nota.pasta_sharepoint = sp.url_pasta(pasta_rel)
        registrar(db, nota, "Arquivos no SharePoint", f"{enviados} arquivo(s) em {settings().sharepoint_pasta}/{pasta_rel}")
    return enviados


def sincronizar_pendentes() -> dict:
    """Roda a cada verificação: tenta de novo o que falhou antes (rede, permissão, arquivo aberto...)."""
    if not habilitado():
        return {"enviados": 0, "erros": 0}
    ok = erros = 0
    with SessionLocal() as db:
        ids = db.scalars(select(Nota.id).join(Documento, Documento.nota_id == Nota.id).where(
            Nota.status.notin_([Status.CONFERENCIA, Status.IGNORADA]), Documento.nome_final != "",
            func.coalesce(Documento.sharepoint_nome, "") != Documento.nome_final).distinct()).all()
        for nota_id in ids:
            nota = db.get(Nota, nota_id)
            try:
                ok += sincronizar_nota(db, nota)
                db.commit()
            except (ErroSharePoint, httpx.HTTPError, RuntimeError) as e:
                db.rollback()
                erros += 1
                log.warning("SharePoint: nota #%s pendente: %s", nota_id, e)
    return {"enviados": ok, "erros": erros}


def enviar_planilha(conteudo: bytes) -> None:
    if not habilitado():
        return
    try:
        cliente().enviar("CONTROLE_NOTAS.xlsx", conteudo)
    except (ErroSharePoint, httpx.HTTPError, RuntimeError) as e:  # ex.: alguém editando a planilha (HTTP 423)
        log.warning("Planilha não atualizada no SharePoint: %s", e)
