"""Robô da caixa: roda no GitHub Actions a cada 15 min.

1. Lê a Caixa de Entrada da prestacaocontasti@ e cria as notas (pré-preenchidas) no Supabase.
2. Avisa o aprovador por e-mail quando há notas aguardando o "de acordo".

    python -m worker.robo
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date

from .classify import TipoDoc, classificar, deve_ignorar
from .extract import Dados, extrair_com_ia, extrair_texto, extrair_xml, so_digitos, texto_pdf
from .graph import Graph, Mensagem, data_iso
from .naming import apelido_sugerido
from .sugestao import sugerir
from .supa import Supabase

log = logging.getLogger("robo")
ABERTAS = "(Em conferência,Aguardando aprovação)"


@dataclass
class Arquivo:
    doc: dict
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


def _cita_numero(numero: str, texto: str) -> bool:
    return bool(numero) and re.search(rf"(?<!\d)0*{re.escape(numero)}(?!\d)", texto) is not None


def agrupar(arquivos: list[Arquivo]) -> list[Grupo]:
    """Uma nota por documento principal; XML e PDF do mesmo número juntos; boleto/MC vão para a nota que citam."""
    principais = [a for a in arquivos if a.tipo in (TipoDoc.XML, TipoDoc.NF, TipoDoc.FT)]
    compl = [a for a in arquivos if a.tipo in (TipoDoc.BOLETO, TipoDoc.MC, TipoDoc.OUTRO)]
    grupos: list[Grupo] = []
    for a in sorted(principais, key=lambda x: x.tipo != TipoDoc.XML):
        alvo = next((g for g in grupos if a.dados.numero and g.numero == a.dados.numero), None)
        if alvo is None and a.tipo != TipoDoc.XML and len(grupos) == 1 \
                and not any(p.tipo == a.tipo for p in grupos[0].principais):
            alvo = grupos[0]
        if alvo is None:
            alvo = Grupo()
            grupos.append(alvo)
        alvo.principais.append(a)
    for c in compl:
        busca = f"{c.doc['nome_original']} {c.texto}"
        alvo = next((g for g in grupos if _cita_numero(g.numero, busca)), None) or (grupos[0] if grupos else None)
        if alvo is None:
            alvo = Grupo()
            grupos.append(alvo)
        alvo.complementares.append(c)
    return grupos


class Robo:
    def __init__(self, sb: Supabase, graph) -> None:
        self.sb, self.graph = sb, graph
        self.filiais = {f["cnpj"]: f for f in sb.select("filiais", select="*")}

    # ------------------------------------------------------------ caixa
    def verificar_caixa(self) -> dict:
        resumo = {"emails": 0, "notas": 0, "ignorados": 0, "erros": 0}
        for msg in self.graph.mensagens_novas():
            if self.sb.select("emails", select="id", graph_id=f"eq.{msg.id}"):
                continue
            try:
                n = self.processar(msg)
                resumo["emails"] += 1
                resumo["notas" if n else "ignorados"] += n or 1
                if n:
                    self.graph.mover_para_processados(msg.id)
            except Exception:
                resumo["erros"] += 1
                log.exception("Erro no e-mail %s", msg.assunto)
        return resumo

    def processar(self, msg: Mensagem) -> int:
        anexos = [a for a in (self.graph.anexos(msg) if msg.tem_anexos else [])
                  if not deve_ignorar(a.nome, a.inline, len(a.conteudo))]
        email = self.sb.insert("emails", {
            "graph_id": msg.id, "remetente": msg.remetente, "assunto": msg.assunto[:500],
            "recebido_em": data_iso(msg.recebido_em), "preview": msg.preview, "web_link": msg.web_link,
            "tipo": "nota" if anexos else "sem_anexo"})[0]
        if not anexos:
            return 0

        arquivos = []
        for a in anexos:
            caminho = f"entrada/{email['id']}/{re.sub(r'[^A-Za-z0-9._ -]', '_', a.nome)}"
            self.sb.upload(caminho, a.conteudo, a.content_type)
            if a.nome.lower().endswith(".xml"):
                dados = extrair_xml(a.conteudo)
                tipo, texto = (TipoDoc.XML, "") if dados else (TipoDoc.OUTRO, "")
                dados = dados or Dados()
            else:
                texto = texto_pdf(a.conteudo)
                tipo = classificar(a.nome, texto)
                dados = extrair_texto(texto, tipo)
            doc = {"email_id": email["id"], "tipo": str(tipo), "nome_original": a.nome, "caminho": caminho,
                   "sha256": hashlib.sha256(a.conteudo).hexdigest()}
            arquivos.append(Arquivo(doc, tipo, dados, a.conteudo, texto))

        criadas = 0
        for grupo in agrupar(arquivos):
            if not grupo.principais and self.anexar_a_existente(grupo):
                continue
            self.criar_nota(email, grupo)
            criadas += 1
        return criadas

    def anexar_a_existente(self, grupo: Grupo) -> bool:
        for c in grupo.complementares:
            for cnpj in c.dados.cnpjs_encontrados:
                for nota in self.sb.select("notas", select="id,numero,vencimento", cnpj_emitente=f"eq.{cnpj}",
                                           status=f"in.{ABERTAS}"):
                    if _cita_numero(nota["numero"], f"{c.doc['nome_original']} {c.texto}"):
                        self.sb.insert("documentos", [{**a.doc, "nota_id": nota["id"]} for a in grupo.complementares])
                        if c.dados.vencimento and not nota["vencimento"]:
                            self.sb.update("notas", {"vencimento": c.dados.vencimento.isoformat()}, id=f"eq.{nota['id']}")
                        self.sb.insert("eventos", {"nota_id": nota["id"], "acao": "Documento recebido",
                                                   "detalhe": "Boleto/memória chegou em outro e-mail"})
                        return True
        return False

    def criar_nota(self, email: dict, grupo: Grupo) -> dict:
        dados = Dados()
        for a in sorted(grupo.principais, key=lambda x: x.tipo != TipoDoc.XML):
            dados.mesclar(a.dados)
        boleto = next((c for c in grupo.complementares if c.tipo == TipoDoc.BOLETO), None)
        if boleto:
            dados.mesclar(Dados(vencimento=boleto.dados.vencimento, cnpjs_encontrados=boleto.dados.cnpjs_encontrados))
        if not (dados.numero and dados.valor and dados.cnpj_emitente):
            pdf = next((a for a in grupo.principais if a.tipo in (TipoDoc.NF, TipoDoc.FT)), None) or boleto
            if pdf and (ia := extrair_com_ia(pdf.conteudo, pdf.tipo)):
                dados = ia.mesclar(dados) if dados.origem != "xml" else dados.mesclar(ia)

        if not dados.cnpj_tomador:
            dados.cnpj_tomador = next((c for c in dados.cnpjs_encontrados if c in self.filiais), "")
        if dados.cnpj_emitente in self.filiais:
            dados.cnpj_emitente = next((c for c in dados.cnpjs_encontrados if c not in self.filiais), "")
        if not dados.razao_emitente:
            dados.razao_emitente = dados.razoes.get(dados.cnpj_emitente, "")

        tipo_p = next((a.tipo for a in grupo.principais if a.tipo in (TipoDoc.NF, TipoDoc.FT)), TipoDoc.NF)
        nota = {
            "email_id": email["id"], "tipo_doc": "FT" if tipo_p == TipoDoc.FT else "NF",
            "numero": dados.numero, "serie": dados.serie, "chave_acesso": dados.chave_acesso,
            "cnpj_emitente": so_digitos(dados.cnpj_emitente), "cnpj_tomador": so_digitos(dados.cnpj_tomador),
            "razao_social": dados.razao_emitente, "descricao": dados.descricao, "valor": dados.valor,
            "emissao": dados.emissao.isoformat() if dados.emissao else None,
            "vencimento": dados.vencimento.isoformat() if dados.vencimento else None,
            "origem_dados": dados.origem or "manual", "empresa": "", "filial": "", "prestador": "", "fornecedor": "",
        }
        self.preencher(nota, dados.fantasia_emitente)
        nota["alertas"] = self.alertas(nota, boleto.dados.valor if boleto else None)
        salva = self.sb.insert("notas", nota)[0]
        docs = [{**a.doc, "nota_id": salva["id"]} for a in grupo.principais + grupo.complementares]
        self.sb.insert("documentos", docs)
        self.sb.insert("eventos", {"nota_id": salva["id"], "acao": "Nota recebida",
                                   "detalhe": f"E-mail de {email['remetente']}: {email['assunto']}"})
        return salva

    def preencher(self, nota: dict, fantasia: str = "") -> None:
        tomador = nota["cnpj_tomador"].zfill(14) if nota["cnpj_tomador"] else ""
        f = self.filiais.get(tomador) or next(
            (x for c, x in self.filiais.items() if tomador and c[:8] == tomador[:8]), None)
        if f:
            nota["empresa"] = f["empresa"]
            nota["filial"] = f["filial"] if f["cnpj"] == tomador else ""
        forn = self.sb.select("fornecedores", select="*", cnpj=f"eq.{nota['cnpj_emitente']}") if nota["cnpj_emitente"] else []
        if forn:
            forn = forn[0]
            nota["prestador"] = forn["apelido"]
            nota["razao_social"] = nota["razao_social"] or forn["razao"]
            cods = forn.get("codigos") or {}
            nota["fornecedor"] = cods.get(nota["empresa"]) or cods.get("*", "")
        else:
            nota["prestador"] = apelido_sugerido(fantasia, nota["razao_social"])
        nota["_fornecedor_cadastrado"] = bool(forn)
        hist = self.sb.select("historico", select="*", prestador=f"eq.{nota['prestador']}",
                              order="data_ref.desc.nullslast,id.desc", limit="300") if nota["prestador"] else []
        campos, exp = sugerir(hist, nota["prestador"], nota["empresa"], nota["descricao"], nota["fornecedor"])
        for k in ("despesa", "produto", "cc", "conta_contabil", "fornecedor", "filial"):
            if campos.get(k) and not nota.get(k):
                nota[k] = campos[k]
        if not nota["descricao"] and campos.get("descricao_modelo"):
            nota["descricao"] = campos["descricao_modelo"]
            exp += " — descrição copiada do último lançamento, ajuste a competência"
        nota["sugestao"] = exp

    def alertas(self, nota: dict, valor_boleto: float | None = None) -> list[str]:
        a = []
        dup = []
        if nota["chave_acesso"]:
            dup = self.sb.select("notas", select="id,status", chave_acesso=f"eq.{nota['chave_acesso']}", status="neq.Ignorada")
        if not dup and nota["cnpj_emitente"] and nota["numero"]:
            dup = self.sb.select("notas", select="id,status", cnpj_emitente=f"eq.{nota['cnpj_emitente']}",
                                 numero=f"eq.{nota['numero']}", status="neq.Ignorada")
        if dup:
            a.append(f"Possível DUPLICIDADE com a nota #{dup[0]['id']} ({dup[0]['status']})")
        elif nota["prestador"] and nota["numero"] and self.sb.select(
                "historico", select="id", prestador=f"eq.{nota['prestador']}", nfs=f"eq.{nota['numero']}", limit="1"):
            a.append(f"NFS {nota['numero']} de {nota['prestador']} já consta na planilha")
        if nota["cnpj_emitente"] and not nota.pop("_fornecedor_cadastrado"):
            a.append("Fornecedor sem cadastro (CNPJ novo): confira prestador e código do fornecedor no Protheus")
        elif not nota["fornecedor"]:
            a.append(f"Sem código de fornecedor para {nota['prestador']} na empresa {nota['empresa'] or '?'}")
        nota.pop("_fornecedor_cadastrado", None)
        if not nota["empresa"]:
            a.append("Empresa/filial não identificada pelo CNPJ do tomador")
        faltando = [n for n, k in (("número", "numero"), ("valor", "valor"), ("vencimento", "vencimento")) if not nota[k]]
        if faltando:
            a.append("Não foi possível ler: " + ", ".join(faltando))
        if nota["vencimento"] and (date.fromisoformat(nota["vencimento"]) - date.today()).days <= 3:
            a.append(f"Vencimento próximo ou vencido: {date.fromisoformat(nota['vencimento']):%d/%m/%Y}")
        if valor_boleto and nota["valor"] and abs(float(nota["valor"]) - valor_boleto) > 0.01:
            a.append(f"Valor do boleto (R$ {valor_boleto:.2f}) difere do valor da nota".replace(".", ","))
        return a

    # ------------------------------------------------------------ aviso ao aprovador
    def avisar_aprovador(self) -> int:
        pendentes = self.sb.select("notas", select="id,prestador,tipo_doc,numero,empresa,valor,vencimento",
                                   status="eq.Aguardando aprovação", notificado="eq.false", order="id")
        if not pendentes:
            return 0
        aprovadores = [p["email"] for p in self.sb.select("perfis", select="email", papel="eq.aprovador")]
        site = os.environ.get("SITE_URL", "")
        linhas = "".join(
            f"<tr><td>#{n['id']}</td><td>{n['prestador']}</td><td>{n['tipo_doc']} {n['numero']}</td>"
            f"<td>{n['empresa']}</td><td style='text-align:right'>R$ {float(n['valor'] or 0):,.2f}</td>"
            f"<td>{n['vencimento'] or '—'}</td></tr>".replace(",", "X").replace(".", ",").replace("X", ".")
            for n in pendentes)
        html = (f"<p>Olá,</p><p>Há {len(pendentes)} nota(s) aguardando o seu <b>de acordo</b> na Central de Notas:</p>"
                f"<table cellpadding='6' style='border-collapse:collapse'>{linhas}</table>"
                f"<p><a href='{site}'>Abrir a Central de Notas</a></p>")
        if aprovadores:
            self.graph.enviar(aprovadores, f"Central de Notas: {len(pendentes)} nota(s) aguardando seu de acordo", html)
        for n in pendentes:
            self.sb.update("notas", {"notificado": True}, id=f"eq.{n['id']}")
        return len(pendentes)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    robo = Robo(Supabase(), Graph())
    log.info("Caixa: %s", robo.verificar_caixa())
    log.info("Avisos enviados ao aprovador: %s", robo.avisar_aprovador())


if __name__ == "__main__":
    main()
