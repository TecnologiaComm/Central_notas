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

    # Tudo o que precisa sobreviver a reinícios. No Azure App Service: PASTA_DADOS=/home/data
    pasta_dados: Path = RAIZ / "data"
    pasta_arquivos: Path | None = None  # padrão: <PASTA_DADOS>/arquivos
    database_url: str = ""  # padrão: SQLite em <PASTA_DADOS>/notas.db

    url_base: str = "http://localhost:8000"
    segredo_app: str = "dev-inseguro"
    intervalo_verificacao_min: int = 5
    modo_demo: bool = False

    # Login Microsoft (Entra ID) via autenticação do App Service ("Easy Auth").
    # Só ligue atrás do App Service com a autenticação configurada: os cabeçalhos X-MS-CLIENT-PRINCIPAL-*
    # só são confiáveis porque o App Service remove os que vierem do navegador.
    login_obrigatorio: bool = False
    usuarios_permitidos: str = ""  # e-mails e/ou domínios separados por vírgula; vazio = qualquer conta do tenant

    # SharePoint: cópia dos arquivos renomeados e da planilha (vazio = só a pasta local)
    sharepoint_site: str = ""  # ex.: commcenter.sharepoint.com:/sites/PrestacaodeContasTI
    sharepoint_biblioteca: str = "Documentos"
    sharepoint_pasta: str = "Notas"

    anthropic_api_key: str = ""
    modelo_ia: str = "claude-sonnet-4-5"


@lru_cache
def settings() -> Settings:
    s = Settings()
    s.pasta_dados = Path(s.pasta_dados).resolve()
    s.pasta_dados.mkdir(parents=True, exist_ok=True)
    s.pasta_arquivos = Path(s.pasta_arquivos or s.pasta_dados / "arquivos").resolve()
    s.pasta_arquivos.mkdir(parents=True, exist_ok=True)
    s.database_url = s.database_url or f"sqlite:///{s.pasta_dados / 'notas.db'}"
    return s


def arquivo_config(nome: str) -> Path | None:
    """Arquivos de negócio: <PASTA_DADOS>/config (carga feita pelo app) > config/ > config/exemplo/."""
    for pasta in (settings().pasta_dados / "config", PASTA_CONFIG, PASTA_CONFIG / "exemplo"):
        if (pasta / nome).exists():
            return pasta / nome
    return None


def recarregar_config() -> None:
    filiais.cache_clear()
    regras_aprovacao.cache_clear()


def _so_digitos(v: str | None) -> str:
    return "".join(c for c in (v or "") if c.isdigit())


@lru_cache
def filiais() -> list[dict]:
    """[{empresa: 'VMT', filial: '99', cnpj: '05828732006552'}, ...]"""
    caminho = arquivo_config("filiais.yaml")
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) if caminho else {}
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
    """Lê o CSV de dados reais (fora do git); se não existir, usa config/exemplo/<nome>."""
    caminho = arquivo_config(nome)
    if not caminho:
        return []
    with caminho.open(encoding="utf-8-sig") as fh:
        return [{k: (v or "").strip() for k, v in linha.items()} for linha in csv.DictReader(fh, delimiter=";")]


def fornecedores_iniciais() -> list[dict]:
    return _ler_csv("fornecedores.csv")


def historico_inicial() -> list[dict]:
    return _ler_csv("historico.csv")
