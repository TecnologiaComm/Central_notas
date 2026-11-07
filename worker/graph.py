"""Outlook via Microsoft Graph (permissões de aplicativo: Mail.ReadWrite e Mail.Send)."""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from datetime import datetime

import httpx
import msal

GRAPH = "https://graph.microsoft.com/v1.0"


@dataclass
class Anexo:
    nome: str
    content_type: str
    inline: bool
    conteudo: bytes = b""


@dataclass
class Mensagem:
    id: str
    remetente: str
    assunto: str
    recebido_em: str | None
    preview: str
    web_link: str
    tem_anexos: bool
    anexos: list[Anexo] = field(default_factory=list)


class Graph:
    def __init__(self) -> None:
        self.caixa = os.environ.get("CAIXA_NOTAS", "prestacaocontasti@commcenter.com.br")
        self._app = msal.ConfidentialClientApplication(
            os.environ["GRAPH_CLIENT_ID"],
            authority=f"https://login.microsoftonline.com/{os.environ['GRAPH_TENANT_ID']}",
            client_credential=os.environ["GRAPH_CLIENT_SECRET"],
        )
        self.http = httpx.Client(timeout=60)
        self._pasta_proc: str | None = None

    def _req(self, metodo: str, caminho: str, **kw) -> httpx.Response:
        tok = self._app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in tok:
            raise RuntimeError(f"Falha no login do Graph: {tok.get('error_description')}")
        h = {"Authorization": f"Bearer {tok['access_token']}", **kw.pop("headers", {})}
        r = self.http.request(metodo, f"{GRAPH}/users/{self.caixa}{caminho}", headers=h, **kw)
        if r.is_error:
            raise RuntimeError(
                f"Graph respondeu {r.status_code} em {metodo} {caminho.split('?')[0]}: {r.text[:500]}\n"
                f"Permissões no token do app: {permissoes_do_token(tok['access_token']) or 'NENHUMA'} "
                "(precisa de Mail.ReadWrite e Mail.Send como permissões de APLICATIVO, com consentimento do admin)")
        return r

    def mensagens_novas(self, limite: int = 50) -> list[Mensagem]:
        r = self._req("GET", "/mailFolders/inbox/messages", params={
            "$top": limite, "$orderby": "receivedDateTime desc",
            "$select": "id,from,subject,receivedDateTime,bodyPreview,webLink,hasAttachments"}).json()
        return [Mensagem(
            id=m["id"], remetente=(m.get("from") or {}).get("emailAddress", {}).get("address", ""),
            assunto=m.get("subject") or "", recebido_em=m.get("receivedDateTime"),
            preview=m.get("bodyPreview") or "", web_link=m.get("webLink") or "",
            tem_anexos=m.get("hasAttachments", False)) for m in r.get("value", [])]

    def anexos(self, msg: Mensagem) -> list[Anexo]:
        r = self._req("GET", f"/messages/{msg.id}/attachments",
                      params={"$select": "id,name,contentType,isInline"}).json()
        saida = []
        for a in r.get("value", []):
            if a.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue
            conteudo = self._req("GET", f"/messages/{msg.id}/attachments/{a['id']}/$value").content
            saida.append(Anexo(a["name"], a.get("contentType", ""), a.get("isInline", False), conteudo))
        return saida

    def mover_para_processados(self, msg_id: str, nome_pasta: str = "Notas Processadas") -> None:
        if not self._pasta_proc:
            r = self._req("GET", "/mailFolders", params={"$filter": f"displayName eq '{nome_pasta}'"}).json()
            self._pasta_proc = r["value"][0]["id"] if r["value"] else \
                self._req("POST", "/mailFolders", json={"displayName": nome_pasta}).json()["id"]
        self._req("PATCH", f"/messages/{msg_id}", json={"isRead": True})
        self._req("POST", f"/messages/{msg_id}/move", json={"destinationId": self._pasta_proc})

    def enviar(self, para: list[str], assunto: str, html: str) -> None:
        self._req("POST", "/sendMail", json={"message": {
            "subject": assunto, "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": e}} for e in para]}, "saveToSentItems": True})


def permissoes_do_token(token: str) -> list[str]:
    """Lê as permissões (roles) do token — só nomes, nada secreto — para diagnosticar 403."""
    import json
    try:
        corpo = token.split(".")[1]
        corpo += "=" * (-len(corpo) % 4)
        return json.loads(base64.urlsafe_b64decode(corpo)).get("roles", [])
    except Exception:
        return []


def data_iso(v: str | None) -> str | None:
    return datetime.fromisoformat(v.replace("Z", "+00:00")).isoformat() if v else None


def b64(c: bytes) -> str:
    return base64.b64encode(c).decode()
