"""Modelo de dados (SQLAlchemy). SQLite por padrão; troca para SQL Server/Postgres via DATABASE_URL.

Colunas da planilha (layout atual do administrativo):
DESPESA | EMPRESA | PRESTADOR | DESCRIÇÃO | FILIAL | PRODUTO | CC | CONTA CONTABIL | FORNECEDOR | VALOR |
PC | NFS | CHAMADO | STATUS CHAMADO | STATUS NOTA | DATA CHAMADO | VENCIMENTO

- EMPRESA   = sigla (VMT, AXT, LUNA, RCT, VENETO) — também usada no nome dos arquivos
- FILIAL    = código da filial no Protheus (1, 2, 20, 99, 71...)
- PRESTADOR = apelido do fornecedor (TOTVS, ERPWORKS) — usado no nome dos arquivos
- FORNECEDOR= código do fornecedor no Protheus (10DS6V, ZERDG2...)
"""
from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


class Status(StrEnum):
    """Etapa da nota dentro do app."""
    CONFERENCIA = "Em conferência"
    AGUARDANDO = "Aguardando aprovação"
    APROVADA = "Aprovada"
    REPROVADA = "Reprovada"
    LANCADA = "NF lançada"
    IGNORADA = "Ignorada"


# Valores usados hoje nas colunas da planilha
DESPESAS = ["OPEX", "CAPEX"]
STATUS_CHAMADO = ["AGUARDANDO ATENDIMENTO", "EM ATENDIMENTO", "SUSPENSO - APROV", "SUSPENSO - RATEIO", "ENCERRADO"]
STATUS_NOTA = ["AGUARDANDO LANÇAMENTO FISCAL", "NF LANÇADA"]


class TipoDoc(StrEnum):
    NF = "NF"
    FT = "FT"
    XML = "XML"
    BOLETO = "BOLETO"
    MC = "MC"
    OUTRO = "OUTRO"


class Email(Base):
    __tablename__ = "emails"
    id: Mapped[int] = mapped_column(primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(255), unique=True)
    conversation_id: Mapped[str | None] = mapped_column(String(255), index=True)
    remetente: Mapped[str] = mapped_column(String(255), default="")
    assunto: Mapped[str] = mapped_column(String(500), default="")
    recebido_em: Mapped[datetime | None] = mapped_column(DateTime)
    preview: Mapped[str] = mapped_column(Text, default="")
    web_link: Mapped[str] = mapped_column(Text, default="")
    tipo: Mapped[str] = mapped_column(String(30), default="nota")  # nota | resposta_aprovacao | sem_anexo
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Fornecedor(Base):
    """Cadastro por CNPJ (carga inicial: aba Infos). codigos = 'VMT=ZERDG2|AXT=10H7Q5' ('*' = qualquer empresa)."""
    __tablename__ = "fornecedores"
    cnpj: Mapped[str] = mapped_column(String(14), primary_key=True)
    apelido: Mapped[str] = mapped_column(String(80))
    razao: Mapped[str] = mapped_column(String(200), default="")
    codigos: Mapped[str] = mapped_column(Text, default="")

    @property
    def mapa_codigos(self) -> dict[str, str]:
        return dict(p.split("=", 1) for p in (self.codigos or "").split("|") if "=" in p)

    def codigo(self, empresa: str) -> str:
        m = self.mapa_codigos
        return m.get((empresa or "").upper()) or m.get("*", "")

    def definir_codigo(self, empresa: str, codigo: str) -> None:
        if not empresa or not codigo:
            return
        m = self.mapa_codigos
        m[empresa.upper()] = codigo
        self.codigos = "|".join(f"{k}={v}" for k, v in m.items())


class Historico(Base):
    """Linhas já lançadas (planilha antiga + notas conferidas no app). Base das sugestões."""
    __tablename__ = "historico"
    id: Mapped[int] = mapped_column(primary_key=True)
    data_ref: Mapped[date | None] = mapped_column(Date, index=True)
    origem: Mapped[str] = mapped_column(String(40), default="planilha")
    nota_id: Mapped[int | None] = mapped_column(index=True)
    despesa: Mapped[str] = mapped_column(String(20), default="")
    empresa: Mapped[str] = mapped_column(String(20), default="", index=True)
    prestador: Mapped[str] = mapped_column(String(80), default="", index=True)
    descricao: Mapped[str] = mapped_column(Text, default="")
    filial: Mapped[str] = mapped_column(String(10), default="")
    produto: Mapped[str] = mapped_column(String(30), default="")
    cc: Mapped[str] = mapped_column(String(30), default="")
    conta_contabil: Mapped[str] = mapped_column(String(30), default="")
    fornecedor: Mapped[str] = mapped_column(String(20), default="")
    valor: Mapped[float | None] = mapped_column(Numeric(14, 2))
    nfs: Mapped[str] = mapped_column(String(60), default="")


class Nota(Base):
    __tablename__ = "notas"
    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int | None] = mapped_column(ForeignKey("emails.id"))
    status: Mapped[str] = mapped_column(String(30), default=Status.CONFERENCIA, index=True)

    # Dados lidos do documento
    tipo_doc: Mapped[str] = mapped_column(String(2), default="NF")  # NF ou FT (nomenclatura)
    serie: Mapped[str] = mapped_column(String(10), default="")
    chave_acesso: Mapped[str] = mapped_column(String(60), default="", index=True)
    cnpj_emitente: Mapped[str] = mapped_column(String(14), default="", index=True)
    razao_social: Mapped[str] = mapped_column(String(200), default="")
    cnpj_tomador: Mapped[str] = mapped_column(String(14), default="")
    emissao: Mapped[date | None] = mapped_column(Date)
    origem_dados: Mapped[str] = mapped_column(String(30), default="")  # xml | pdf | ia | manual
    sugestao: Mapped[str] = mapped_column(Text, default="")  # de onde vieram as sugestões

    # Colunas da planilha
    despesa: Mapped[str] = mapped_column(String(20), default="")
    empresa: Mapped[str] = mapped_column(String(20), default="")
    prestador: Mapped[str] = mapped_column(String(80), default="")
    descricao: Mapped[str] = mapped_column(Text, default="")
    filial: Mapped[str] = mapped_column(String(10), default="")
    produto: Mapped[str] = mapped_column(String(30), default="")
    cc: Mapped[str] = mapped_column(String(30), default="")
    conta_contabil: Mapped[str] = mapped_column(String(30), default="")
    fornecedor: Mapped[str] = mapped_column(String(20), default="")
    valor: Mapped[float | None] = mapped_column(Numeric(14, 2))
    pc: Mapped[str] = mapped_column(String(30), default="")
    numero: Mapped[str] = mapped_column(String(60), default="")  # NFS
    chamado: Mapped[str] = mapped_column(String(40), default="")
    status_chamado: Mapped[str] = mapped_column(String(40), default="")
    status_nota: Mapped[str] = mapped_column(String(40), default="")
    data_chamado: Mapped[date | None] = mapped_column(Date)
    vencimento: Mapped[date | None] = mapped_column(Date)

    # Controle
    alertas: Mapped[str] = mapped_column(Text, default="")
    aprovadores: Mapped[str] = mapped_column(Text, default="")
    aprovado_por: Mapped[str] = mapped_column(String(255), default="")
    decisao_em: Mapped[datetime | None] = mapped_column(DateTime)
    comentario_aprovacao: Mapped[str] = mapped_column(Text, default="")
    pasta: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    email: Mapped[Email | None] = relationship()
    documentos: Mapped[list["Documento"]] = relationship(back_populates="nota", order_by="Documento.id")
    eventos: Mapped[list["Evento"]] = relationship(back_populates="nota", order_by="Evento.id.desc()")

    @property
    def lista_alertas(self) -> list[str]:
        return [a for a in (self.alertas or "").splitlines() if a.strip()]


class Documento(Base):
    __tablename__ = "documentos"
    id: Mapped[int] = mapped_column(primary_key=True)
    nota_id: Mapped[int | None] = mapped_column(ForeignKey("notas.id"), index=True)
    email_id: Mapped[int | None] = mapped_column(ForeignKey("emails.id"))
    tipo: Mapped[str] = mapped_column(String(10), default=TipoDoc.OUTRO)
    nome_original: Mapped[str] = mapped_column(String(300))
    nome_final: Mapped[str] = mapped_column(String(300), default="")
    caminho: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(120), default="")
    sha256: Mapped[str] = mapped_column(String(64), index=True)

    nota: Mapped[Nota | None] = relationship(back_populates="documentos")


class Evento(Base):
    __tablename__ = "eventos"
    id: Mapped[int] = mapped_column(primary_key=True)
    nota_id: Mapped[int] = mapped_column(ForeignKey("notas.id"), index=True)
    quando: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    quem: Mapped[str] = mapped_column(String(255), default="sistema")
    acao: Mapped[str] = mapped_column(String(80))
    detalhe: Mapped[str] = mapped_column(Text, default="")

    nota: Mapped[Nota] = relationship(back_populates="eventos")


_url = settings().database_url
engine = create_engine(_url, connect_args={"check_same_thread": False} if _url.startswith("sqlite") else {})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def _num(v: str) -> float | None:
    try:
        return round(float(v), 2) if v else None
    except ValueError:
        return None


def iniciar_banco() -> None:
    if _url.startswith("sqlite:///"):
        from pathlib import Path
        Path(_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    from .config import fornecedores_iniciais, historico_inicial
    with SessionLocal() as db:
        for f in fornecedores_iniciais():
            cnpj = "".join(c for c in f.get("cnpj", "") if c.isdigit()).zfill(14)
            if cnpj.strip("0") and not db.get(Fornecedor, cnpj):
                db.add(Fornecedor(cnpj=cnpj, apelido=f.get("apelido", "").upper(),
                                  razao=f.get("razao", ""), codigos=f.get("codigos", "")))
        if db.scalar(select(Historico.id).limit(1)) is None:
            for h in historico_inicial():
                db.add(Historico(
                    data_ref=date.fromisoformat(h["data_ref"]) if h.get("data_ref") else None,
                    origem=f"planilha:{h.get('aba', '')}", valor=_num(h.get("valor", "")),
                    **{k: h.get(k, "") for k in ("despesa", "empresa", "prestador", "descricao", "filial",
                                                 "produto", "cc", "conta_contabil", "fornecedor", "nfs")}))
        db.commit()


def registrar(db, nota: Nota, acao: str, detalhe: str = "", quem: str = "sistema") -> None:
    db.add(Evento(nota_id=nota.id, acao=acao, detalhe=detalhe, quem=quem))
