"""Configurações do app (lidas do .env) e arquivos de configuração de negócio."""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parent.parent
PASTA_CONFIG = RAIZ / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=RAIZ / ".env", extra="ignore")

    graph_tenant_id: str = ""
    graph_client_id: str = ""
    graph_client_secret: str = ""
    caixa_notas: str = "prestacaocontasti@commcenter.com.br"
    pasta_entrada: str = "Inbox"
    pasta_processados: str = "Notas Processadas"

    pasta_arquivos: Path = RAIZ / "data" / "arquivos"
    database_url: str = f"sqlite:///{RAIZ / 'data' / 'notas.db'}"

    url_base: str = "http://localhost:8000"
    segredo_app: str = "dev-inseguro"
    intervalo_verificacao_min: int = 5
    modo_demo: bool = False

    anthropic_api_key: str = ""
    modelo_ia: str = "claude-sonnet-4-5"

    # Protheus (fase 2) — endpoint REST customizado (ver protheus/CENTRALNOTAS.tlpp)
    protheus_url: str = ""  # ex.: http://protheus.comm.local:8181/rest
    protheus_endpoint: str = "/centralnotas/v1/documento-entrada"
    protheus_auth: str = "basic"  # basic | oauth2
    protheus_usuario: str = ""
    protheus_senha: str = ""
    protheus_timeout_s: int = 120
    protheus_verificar_tls: bool = True
    protheus_lancar_automatico: bool = False  # lança sozinho as notas aprovadas


@lru_cache
def protheus_cfg() -> dict:
    """Mapeamentos de negócio para o Protheus (config/protheus.yaml)."""
    caminho = PASTA_CONFIG / "protheus.yaml"
    if not caminho.exists():
        return {}
    return yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}


@lru_cache
def settings() -> Settings:
    s = Settings()
    s.pasta_arquivos = Path(s.pasta_arquivos).resolve()
    s.pasta_arquivos.mkdir(parents=True, exist_ok=True)
    return s


def _so_digitos(v: str | None) -> str:
    return "".join(c for c in (v or "") if c.isdigit())


@lru_cache
def filiais() -> list[dict]:
    """[{empresa: 'VMT', filial: '99', cnpj: '05828732006552'}, ...]"""
    dados = yaml.safe_load((PASTA_CONFIG / "filiais.yaml").read_text(encoding="utf-8"))
    return [{"empresa": str(f["empresa"]).upper(), "filial": str(f["filial"]),
             "cnpj": _so_digitos(str(f["cnpj"])).zfill(14)} for f in dados.get("filiais", [])]


def empresas() -> list[str]:
    return list(dict.fromkeys(f["empresa"] for f in filiais()))


def filial_por_cnpj(cnpj: str | None) -> dict | None:
    cnpj = _so_digitos(cnpj).zfill(14) if cnpj else ""
    if not cnpj:
        return None
    for f in filiais():
        if f["cnpj"] == cnpj:
            return f
    for f in filiais():  # mesma raiz de CNPJ -> ao menos a empresa
        if f["cnpj"][:8] == cnpj[:8]:
            return {**f, "filial": ""}
    return None


@lru_cache
def regras_aprovacao() -> dict:
    return yaml.safe_load((PASTA_CONFIG / "aprovacao.yaml").read_text(encoding="utf-8"))


def _ler_csv(nome: str) -> list[dict]:
    """Lê config/<nome> (dados reais, fora do git); se não existir, usa config/exemplo/<nome>."""
    caminho = PASTA_CONFIG / nome
    if not caminho.exists():
        caminho = PASTA_CONFIG / "exemplo" / nome
    if not caminho.exists():
        return []
    with caminho.open(encoding="utf-8-sig") as fh:
        return [{k: (v or "").strip() for k, v in linha.items()} for linha in csv.DictReader(fh, delimiter=";")]


def fornecedores_iniciais() -> list[dict]:
    return _ler_csv("fornecedores.csv")


def historico_inicial() -> list[dict]:
    return _ler_csv("historico.csv")
