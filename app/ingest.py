"""Leitura da caixa de e-mail -> criação das notas pré-preenchidas para conferência."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select

from . import aprovacao
from .classify import classificar, deve_ignorar
from .config import filial_por_cnpj, filiais, settings
from .extract import Dados, extrair_com_ia, extrair_texto, extrair_xml, so_digitos, texto_pdf
from .graph import Mensagem, cliente
from .models import Documento, Email, Fornecedor, Historico, Nota, SessionLocal, Status, TipoDoc, registrar
from .sugestao import sugerir
from .naming import apelido_sugerido

log = logging.getLogger(__name__)


@dataclass
class Arquivo:
    doc: Documento
    tipo: TipoDoc
    dados: Dados
    conteudo: bytes
    texto: str = ""


@dataclass
class Grupo:
    principais: list[Arquivo] = field(default_factory=list)
    complementares: list[Arquivo] = field(default_factory=list)

    @property
    def numero(self) -> str:
        return next((a.dados.numero for a in self.principais if a.dados.numero), "")


def verificar_caixa() -> dict:
    """Executado periodicamente (e pelo botão 'Verificar agora')."""
    g, s = cliente(), settings()
    resumo = {"emails": 0, "notas": 0, "respostas": 0, "ignorados": 0, "erros": 0}
    with SessionLocal() as db:
        conhecidos = set(db.scalars(select(Email.graph_id)))
        for msg in g.listar_mensagens(s.pasta_entrada, limite=100):
            if msg.id in conhecidos:
                continue
            try:
                r = processar_mensagem(db, msg)
                resumo[r] += 1
                resumo["emails"] += 1
                db.commit()
                if r in ("notas", "respostas"):
                    g.mover_para_processados(msg.id)
            except Exception:
                db.rollback()
                resumo["erros"] += 1
                log.exception("Erro processando e-mail %s (%s)", msg.id, msg.assunto)
    log.info("Verificação da caixa: %s", resumo)
    return resumo


def processar_mensagem(db, msg: Mensagem) -> str:
    resposta = aprovacao.id_nota_no_assunto(msg.assunto)
    email = Email(graph_id=msg.id, conversation_id=msg.conversation_id, remetente=msg.remetente,
                  assunto=msg.assunto[:500], recebido_em=msg.recebido_em, preview=msg.preview,
                  web_link=msg.web_link)
    db.add(email)
    db.flush()

    if resposta:
        email.tipo = "resposta_aprovacao"
        aprovacao.processar_resposta(db, resposta, msg.remetente, msg.corpo_texto, email)
        return "respostas"

    anexos = [a for a in (cliente().baixar_anexos(msg) if msg.tem_anexos else [])
              if not deve_ignorar(a.nome, a.inline, a.tamanho)]
    if not anexos:
        email.tipo = "sem_anexo"
        return "ignorados"

    entrada = settings().pasta_arquivos / "_entrada" / str(email.id)
    entrada.mkdir(parents=True, exist_ok=True)
    arquivos: list[Arquivo] = []
    for a in anexos:
        sha = hashlib.sha256(a.conteudo).hexdigest()
        caminho = entrada / Path(a.nome).name
        caminho.write_bytes(a.conteudo)
        doc = Documento(email_id=email.id, nome_original=a.nome, caminho=str(caminho),
                        content_type=a.content_type, sha256=sha)
        if a.nome.lower().endswith(".xml"):
            dados = extrair_xml(a.conteudo)
            if dados is None:  # XML que não é nota (ex.: evento, cancelamento)
                tipo, dados, texto = TipoDoc.OUTRO, Dados(), ""
            else:
                tipo, texto = TipoDoc.XML, ""
        else:
            texto = texto_pdf(a.conteudo)
            tipo = classificar(a.nome, texto)
            dados = extrair_texto(texto, tipo)
        doc.tipo = tipo
        db.add(doc)
        arquivos.append(Arquivo(doc, tipo, dados, a.conteudo, texto))
    db.flush()

    grupos = agrupar(arquivos)
    if not grupos:
        email.tipo = "sem_anexo"
        return "ignorados"
    for grupo in grupos:
        if not grupo.principais and anexar_a_nota_existente(db, grupo):
            continue
        criar_nota(db, email, grupo)
    return "notas"


def agrupar(arquivos: list[Arquivo]) -> list[Grupo]:
    """Uma nota por documento principal; XML e PDF do mesmo número ficam juntos;
    boletos e memórias vão para a nota com o mesmo número (ou para a única nota do e-mail)."""
    principais = [a for a in arquivos if a.tipo in (TipoDoc.XML, TipoDoc.NF, TipoDoc.FT)]
    compl = [a for a in arquivos if a.tipo in (TipoDoc.BOLETO, TipoDoc.MC, TipoDoc.OUTRO)]
    grupos: list[Grupo] = []
    # XML primeiro: é a fonte mais confiável
    for a in sorted(principais, key=lambda x: x.tipo != TipoDoc.XML):
        alvo = next((g for g in grupos if a.dados.numero and g.numero == a.dados.numero), None)
        if alvo is None and a.tipo != TipoDoc.XML and len(grupos) == 1 \
                and not any(p.tipo == a.tipo for p in grupos[0].principais):
            alvo = grupos[0]  # 1 XML + 1 PDF no mesmo e-mail -> mesma nota
        if alvo is None:
            alvo = Grupo()
            grupos.append(alvo)
        alvo.principais.append(a)

    for c in compl:
        texto_busca = f"{c.doc.nome_original} {c.texto}"
        alvo = next((g for g in grupos if g.numero and re.search(rf"(?<!\d)0*{re.escape(g.numero)}(?!\d)", texto_busca)), None)
        if alvo is None and grupos:
            alvo = grupos[0]
        if alvo is None:
            alvo = Grupo()
            grupos.append(alvo)
        alvo.complementares.append(c)
    return grupos


def anexar_a_nota_existente(db, grupo: Grupo) -> bool:
    """E-mail só com boleto/memória: procura uma nota em aberto do mesmo fornecedor que o documento cite."""
    for c in grupo.complementares:
        cnpjs = set(c.dados.cnpjs_encontrados)
        if not cnpjs:
            continue
        abertas = db.scalars(select(Nota).where(
            Nota.cnpj_emitente.in_(cnpjs),
            Nota.status.in_([Status.CONFERENCIA, Status.AGUARDANDO]))).all()
        for nota in abertas:
            if nota.numero and re.search(rf"(?<!\d)0*{re.escape(nota.numero)}(?!\d)", f"{c.doc.nome_original} {c.texto}"):
                for a in grupo.complementares:
                    a.doc.nota_id = nota.id
                registrar(db, nota, "Documento recebido", "Boleto/memória chegou em outro e-mail e foi vinculado")
                if c.dados.vencimento and not nota.vencimento:
                    nota.vencimento = c.dados.vencimento
                return True
    return False


def criar_nota(db, email: Email, grupo: Grupo) -> Nota:
    dados = Dados()
    for a in sorted(grupo.principais, key=lambda x: x.tipo != TipoDoc.XML):
        dados.mesclar(a.dados)
    boleto = next((c for c in grupo.complementares if c.tipo == TipoDoc.BOLETO), None)
    if boleto:
        dados.mesclar(Dados(vencimento=boleto.dados.vencimento, cnpjs_encontrados=boleto.dados.cnpjs_encontrados))

    # IA só se faltar algo essencial e houver PDF principal
    if not (dados.numero and dados.valor and dados.cnpj_emitente):
        pdf = next((a for a in grupo.principais if a.tipo in (TipoDoc.NF, TipoDoc.FT)), None) or \
              next((c for c in grupo.complementares if c.tipo == TipoDoc.BOLETO), None)
        if pdf and (ia := extrair_com_ia(pdf.conteudo, pdf.tipo)):
            ia.cnpjs_encontrados = []
            # IA tem prioridade sobre as heurísticas de PDF, mas não sobre o XML
            dados = ia.mesclar(dados) if dados.origem != "xml" else dados.mesclar(ia)

    # Tomador: no XML vem direto; no PDF, o CNPJ que bater com uma filial cadastrada
    cnpjs_filiais = {f["cnpj"] for f in filiais()}
    if not dados.cnpj_tomador:
        dados.cnpj_tomador = next((c for c in dados.cnpjs_encontrados if c in cnpjs_filiais), "")
    if dados.cnpj_emitente in cnpjs_filiais:  # heurística pegou o CNPJ errado
        dados.cnpj_emitente = next((c for c in dados.cnpjs_encontrados if c not in cnpjs_filiais), "")
    if not dados.razao_emitente:
        dados.razao_emitente = dados.razoes.get(dados.cnpj_emitente, "")

    tipo_principal = next((a.tipo for a in grupo.principais if a.tipo in (TipoDoc.NF, TipoDoc.FT)), TipoDoc.NF)
    nota = Nota(
        email_id=email.id, status=Status.CONFERENCIA, tipo_doc="FT" if tipo_principal == TipoDoc.FT else "NF",
        numero=dados.numero, serie=dados.serie, chave_acesso=dados.chave_acesso,
        cnpj_emitente=so_digitos(dados.cnpj_emitente), cnpj_tomador=so_digitos(dados.cnpj_tomador),
        razao_social=dados.razao_emitente, emissao=dados.emissao, valor=dados.valor,
        vencimento=dados.vencimento, descricao=dados.descricao, origem_dados=dados.origem or "manual",
    )
    preencher_sugestoes(db, nota, dados.fantasia_emitente)

    db.add(nota)
    db.flush()
    for a in grupo.principais + grupo.complementares:
        a.doc.nota_id = nota.id

    nota.alertas = "\n".join(calcular_alertas(db, nota, boleto.dados.valor if boleto else None))
    registrar(db, nota, "Nota recebida", f"E-mail de {email.remetente}: {email.assunto}")
    return nota


def preencher_sugestoes(db, nota: Nota, fantasia: str = "") -> None:
    """EMPRESA/FILIAL pelo CNPJ do tomador; PRESTADOR/FORNECEDOR pelo cadastro; resto pelo histórico."""
    if f := filial_por_cnpj(nota.cnpj_tomador):
        nota.empresa, nota.filial = f["empresa"], f["filial"]

    forn = db.get(Fornecedor, nota.cnpj_emitente) if nota.cnpj_emitente else None
    if forn:
        nota.prestador = forn.apelido
        nota.razao_social = nota.razao_social or forn.razao
        nota.fornecedor = forn.codigo(nota.empresa)
    else:
        nota.prestador = apelido_sugerido(fantasia, nota.razao_social)

    campos, explicacao = sugerir(db, nota.prestador, nota.empresa, nota.descricao, nota.fornecedor)
    for k in ("despesa", "produto", "cc", "conta_contabil", "fornecedor", "filial"):
        if campos.get(k) and not getattr(nota, k):
            setattr(nota, k, campos[k])
    if not nota.descricao and campos.get("descricao_modelo"):
        nota.descricao = campos["descricao_modelo"]
        explicacao += " — descrição copiada do último lançamento, ajuste a competência"
    nota.sugestao = explicacao


def calcular_alertas(db, nota: Nota, valor_boleto: float | None = None) -> list[str]:
    alertas = []
    filtro = [Nota.id != nota.id, Nota.status != Status.IGNORADA]
    dup = None
    if nota.chave_acesso:
        dup = db.scalar(select(Nota).where(Nota.chave_acesso == nota.chave_acesso, *filtro))
    if not dup and nota.cnpj_emitente and nota.numero:
        dup = db.scalar(select(Nota).where(Nota.cnpj_emitente == nota.cnpj_emitente,
                                           Nota.numero == nota.numero, *filtro))
    if dup:
        alertas.append(f"Possível DUPLICIDADE com a nota #{dup.id} ({dup.status})")
    elif nota.prestador and nota.numero:
        h = db.scalar(select(Historico).where(Historico.prestador == nota.prestador, Historico.nfs == nota.numero))
        if h:
            alertas.append(f"NFS {nota.numero} de {nota.prestador} já consta na planilha ({h.origem.split(':')[-1]})")
    if nota.cnpj_emitente and not db.get(Fornecedor, nota.cnpj_emitente):
        alertas.append("Fornecedor sem cadastro (CNPJ novo): confira prestador e código do fornecedor no Protheus")
    elif not nota.fornecedor:
        alertas.append(f"Sem código de fornecedor para {nota.prestador} na empresa {nota.empresa or '?'}")
    if not nota.empresa:
        alertas.append("Empresa/filial não identificada pelo CNPJ do tomador")
    faltando = [n for n, v in (("número", nota.numero), ("valor", nota.valor), ("vencimento", nota.vencimento)) if not v]
    if faltando:
        alertas.append("Não foi possível ler: " + ", ".join(faltando))
    if nota.vencimento and (nota.vencimento - date.today()).days <= 3:
        alertas.append(f"Vencimento próximo ou vencido: {nota.vencimento:%d/%m/%Y}")
    if valor_boleto and nota.valor and abs(float(nota.valor) - valor_boleto) > 0.01:
        alertas.append(f"Valor do boleto (R$ {valor_boleto:,.2f}) difere do valor da nota".replace(",", "X").replace(".", ",").replace("X", "."))
    return alertas
