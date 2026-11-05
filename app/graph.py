"""Cliente Microsoft Graph (Outlook) com autenticação de aplicativo (client credentials).

Permissões de aplicativo no Entra ID: Mail.ReadWrite e Mail.Send.
Recomendado: limitar o app à caixa de notas com uma ApplicationAccessPolicy no Exchange Online,
para que ele não consiga ler outras caixas da empresa.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
import msal

from .config import RAIZ, settings

GRAPH = "https://graph.microsoft.com/v1.0"


@dataclass
class Anexo:
    id: str
    nome: str
    content_type: str
    tamanho: int
    inline: bool
    conteudo: bytes | None = None


@dataclass
class Mensagem:
    id: str
    conversation_id: str
    remetente: str
    assunto: str
    recebido_em: datetime | None
    preview: str
    corpo_texto: str
    web_link: str
    tem_anexos: bool
    anexos: list[Anexo] = field(default_factory=list)


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)


class GraphClient:
    def __init__(self) -> None:
        s = settings()
        self.caixa = s.caixa_notas
        self._app = msal.ConfidentialClientApplication(
            s.graph_client_id,
            authority=f"https://login.microsoftonline.com/{s.graph_tenant_id}",
            client_credential=s.graph_client_secret,
        )
        self._http = httpx.Client(timeout=60)
        self._pastas: dict[str, str] = {}

    # ---------- infra ----------
    def _token(self) -> str:
        r = self._app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in r:
            raise RuntimeError(f"Falha ao autenticar no Graph: {r.get('error_description')}")
        return r["access_token"]

    def _req(self, metodo: str, caminho: str, **kw) -> httpx.Response:
        url = caminho if caminho.startswith("http") else f"{GRAPH}/users/{self.caixa}{caminho}"
        h = {"Authorization": f"Bearer {self._token()}", **kw.pop("headers", {})}
        r = self._http.request(metodo, url, headers=h, **kw)
        r.raise_for_status()
        return r

    def _id_pasta(self, nome: str, criar: bool = False) -> str:
        if nome.lower() in ("inbox", "caixa de entrada"):
            return "inbox"
        if nome in self._pastas:
            return self._pastas[nome]
        r = self._req("GET", "/mailFolders", params={"$filter": f"displayName eq '{nome}'"}).json()
        if r["value"]:
            self._pastas[nome] = r["value"][0]["id"]
        elif criar:
            self._pastas[nome] = self._req("POST", "/mailFolders", json={"displayName": nome}).json()["id"]
        else:
            raise RuntimeError(f"Pasta '{nome}' não encontrada na caixa {self.caixa}")
        return self._pastas[nome]

    # ---------- leitura ----------
    def listar_mensagens(self, pasta: str, limite: int = 50) -> list[Mensagem]:
        campos = "id,conversationId,from,subject,receivedDateTime,bodyPreview,body,webLink,hasAttachments"
        r = self._req(
            "GET", f"/mailFolders/{self._id_pasta(pasta)}/messages",
            params={"$top": limite, "$orderby": "receivedDateTime asc", "$select": campos},
            headers={"Prefer": 'outlook.body-content-type="text"'},
        ).json()
        return [
            Mensagem(
                id=m["id"], conversation_id=m.get("conversationId", ""),
                remetente=(m.get("from") or {}).get("emailAddress", {}).get("address", ""),
                assunto=m.get("subject") or "", recebido_em=_parse_dt(m.get("receivedDateTime")),
                preview=m.get("bodyPreview") or "", corpo_texto=(m.get("body") or {}).get("content", ""),
                web_link=m.get("webLink") or "", tem_anexos=m.get("hasAttachments", False),
            )
            for m in r.get("value", [])
        ]

    def baixar_anexos(self, msg: Mensagem) -> list[Anexo]:
        r = self._req("GET", f"/messages/{msg.id}/attachments",
                      params={"$select": "id,name,contentType,size,isInline"}).json()
        anexos = []
        for a in r.get("value", []):
            if a.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue  # ignora itens anexados (e-mail dentro de e-mail) e links de nuvem
            conteudo = self._req("GET", f"/messages/{msg.id}/attachments/{a['id']}/$value").content
            anexos.append(Anexo(a["id"], a["name"], a.get("contentType", ""), a.get("size", 0),
                                a.get("isInline", False), conteudo))
        return anexos

    # ---------- ações ----------
    def mover_para_processados(self, msg_id: str) -> None:
        destino = self._id_pasta(settings().pasta_processados, criar=True)
        self._req("PATCH", f"/messages/{msg_id}", json={"isRead": True})
        self._req("POST", f"/messages/{msg_id}/move", json={"destinationId": destino})

    def enviar_email(self, para: list[str], assunto: str, html: str,
                     anexos: list[tuple[str, bytes, str]] = ()) -> None:
        """anexos: (nome, conteúdo, content_type). Limite do sendMail: ~3 MB por anexo."""
        mensagem = {
            "subject": assunto,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": e}} for e in para],
            "attachments": [
                {"@odata.type": "#microsoft.graph.fileAttachment", "name": n,
                 "contentType": ct, "contentBytes": base64.b64encode(c).decode()}
                for n, c, ct in anexos
            ],
        }
        self._req("POST", "/sendMail", json={"message": mensagem, "saveToSentItems": True})


class GraphDemo:
    """Simula a caixa de e-mail usando arquivos em data/demo — para testar sem credenciais."""

    def __init__(self) -> None:
        self.pasta = RAIZ / "data" / "demo"
        self.enviados = RAIZ / "data" / "demo_enviados"
        self.processados: set[str] = set()
        estado = self.pasta / "_processados.json"
        if estado.exists():
            self.processados = set(json.loads(estado.read_text()))

    def listar_mensagens(self, pasta: str, limite: int = 50) -> list[Mensagem]:
        msgs = []
        for arq in sorted(self.pasta.glob("*.json")):
            if arq.name.startswith("_"):
                continue
            d = json.loads(arq.read_text(encoding="utf-8"))
            if d["id"] in self.processados:
                continue
            msgs.append(Mensagem(
                id=d["id"], conversation_id=d.get("conversation_id", d["id"]),
                remetente=d["remetente"], assunto=d["assunto"],
                recebido_em=_parse_dt(d.get("recebido_em")), preview=d.get("corpo", "")[:200],
                corpo_texto=d.get("corpo", ""), web_link="", tem_anexos=bool(d.get("anexos")),
                anexos=[Anexo(str(i), Path(a).name, "", 0, False) for i, a in enumerate(d.get("anexos", []))],
            ))
        return msgs[:limite]

    def baixar_anexos(self, msg: Mensagem) -> list[Anexo]:
        for a in msg.anexos:
            a.conteudo = (self.pasta / "anexos" / a.nome).read_bytes()
        return msg.anexos

    def mover_para_processados(self, msg_id: str) -> None:
        self.processados.add(msg_id)
        (self.pasta / "_processados.json").write_text(json.dumps(sorted(self.processados)))

    def enviar_email(self, para, assunto, html, anexos=()) -> None:
        self.enviados.mkdir(parents=True, exist_ok=True)
        nome = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (self.enviados / f"{nome}.html").write_text(
            f"<p><b>Para:</b> {', '.join(para)}<br><b>Assunto:</b> {assunto}<br>"
            f"<b>Anexos:</b> {', '.join(a[0] for a in anexos)}</p><hr>{html}", encoding="utf-8")


_cliente = None


def cliente():
    global _cliente
    if _cliente is None:
        _cliente = GraphDemo() if settings().modo_demo else GraphClient()
    return _cliente
