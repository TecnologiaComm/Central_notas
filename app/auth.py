"""Quem está usando o app.

No Azure App Service, a autenticação da plataforma ("Easy Auth", provedor Microsoft/Entra ID) faz o login
com a conta da Comm e repassa a identidade nos cabeçalhos X-MS-CLIENT-PRINCIPAL-*. O App Service remove
esses cabeçalhos quando vêm do navegador, por isso eles só são lidos com LOGIN_OBRIGATORIO=true.

Fora do Azure (servidor interno / demo): X-Remote-User de um proxy autenticado, ou o nome digitado na tela.
"""
from __future__ import annotations

import base64
import json
from html import escape
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import settings

# Abertas sem login do app: verificação de saúde do Azure e arquivos da própria plataforma de login.
PUBLICAS = ("/saude", "/.auth/")
# Abertas a qualquer conta logada (o link é assinado por aprovador), mesmo fora de USUARIOS_PERMITIDOS.
DO_APROVADOR = ("/aprovacao/",)
_CLAIMS_EMAIL = ("preferred_username", "email", "upn",
                 "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
                 "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn")
_CLAIMS_NOME = ("name", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name")


def principal(request: Request) -> dict | None:
    """{'email': ..., 'nome': ...} da conta logada pelo App Service, ou None."""
    if not settings().login_obrigatorio:
        return None
    email = request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME", "")
    nome = ""
    bruto = request.headers.get("X-MS-CLIENT-PRINCIPAL", "")
    if bruto:
        try:
            dados = json.loads(base64.b64decode(bruto + "=" * (-len(bruto) % 4)))
            claims = {c.get("typ"): c.get("val") for c in dados.get("claims", [])}
            email = email or next((claims[c] for c in _CLAIMS_EMAIL if claims.get(c)), "")
            nome = next((claims[c] for c in _CLAIMS_NOME if claims.get(c)), "")
        except (ValueError, TypeError, AttributeError):
            pass
    return {"email": email.lower(), "nome": nome or email} if email else None


def usuario(request: Request) -> str:
    p = principal(request)
    if p:
        return p["email"]
    if settings().login_obrigatorio:
        return ""
    return request.headers.get("X-Remote-User") or request.cookies.get("usuario") or "analista"


def permitido(email: str) -> bool:
    regras = [r.strip().lower() for r in settings().usuarios_permitidos.split(",") if r.strip()]
    if not regras:
        return True
    email = email.lower()
    return any(email == r or (r.startswith("@") and email.endswith(r)) for r in regras)


async def exigir_login(request: Request, call_next):
    """Middleware: sem conta logada -> tela de login da Microsoft; conta fora da lista -> 403."""
    s, caminho = settings(), request.url.path
    if not s.login_obrigatorio or caminho.startswith(PUBLICAS):
        return await call_next(request)
    p = principal(request)
    if not p:
        destino = caminho + (f"?{request.url.query}" if request.url.query else "")
        if request.method != "GET":
            destino = "/"
        return RedirectResponse(f"/.auth/login/aad?post_login_redirect_uri={quote(destino, safe='')}", 302)
    if not caminho.startswith(DO_APROVADOR) and not permitido(p["email"]):
        return HTMLResponse(f"<p>A conta <b>{escape(p['email'])}</b> não tem acesso à Central de Notas. "
                            f"Peça a liberação à TI.</p><p><a href='/.auth/logout'>Sair</a></p>", 403)
    return await call_next(request)
