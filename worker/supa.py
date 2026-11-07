"""Cliente mínimo do Supabase (REST + Storage) usando a service role key (só no GitHub Actions)."""
from __future__ import annotations

import os
from urllib.parse import quote

import httpx


class Supabase:
    def __init__(self, url: str | None = None, chave: str | None = None) -> None:
        self.url = (url or os.environ["SUPABASE_URL"]).rstrip("/")
        chave = chave or os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self.http = httpx.Client(timeout=60, headers={"apikey": chave, "Authorization": f"Bearer {chave}"})

    # ---------- tabelas ----------
    def select(self, tabela: str, **params) -> list[dict]:
        r = self.http.get(f"{self.url}/rest/v1/{tabela}", params=params)
        r.raise_for_status()
        return r.json()

    def insert(self, tabela: str, linhas: dict | list[dict], upsert: str | None = None) -> list[dict]:
        headers = {"Prefer": "return=representation"}
        params = {}
        if upsert:
            headers["Prefer"] += ",resolution=merge-duplicates"
            params["on_conflict"] = upsert
        r = self.http.post(f"{self.url}/rest/v1/{tabela}", json=linhas, headers=headers, params=params)
        r.raise_for_status()
        return r.json()

    def update(self, tabela: str, valores: dict, **filtro) -> list[dict]:
        r = self.http.patch(f"{self.url}/rest/v1/{tabela}", json=valores, params=filtro,
                            headers={"Prefer": "return=representation"})
        r.raise_for_status()
        return r.json()

    # ---------- arquivos ----------
    def upload(self, caminho: str, conteudo: bytes, content_type: str = "application/octet-stream") -> None:
        r = self.http.post(f"{self.url}/storage/v1/object/notas/{quote(caminho)}", content=conteudo,
                           headers={"Content-Type": content_type or "application/octet-stream", "x-upsert": "true"})
        r.raise_for_status()
