"""Robô da caixa ponta a ponta com Supabase e Outlook simulados (dados de exemplo)."""
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tests"))

from worker.graph import Anexo, Mensagem  # noqa: E402
from worker.robo import Robo  # noqa: E402


class FakeSupabase:
    def __init__(self, tabelas):
        self.t = {k: [dict(r) for r in v] for k, v in tabelas.items()}
        self.ids = {k: len(v) for k, v in self.t.items()}
        self.arquivos = {}

    def _filtra(self, linhas, filtro):
        for campo, cond in filtro.items():
            if campo in ("select", "order", "limit"):
                continue
            op, val = cond.split(".", 1)
            if op == "eq":
                linhas = [r for r in linhas if str(r.get(campo, "")).lower() == val.lower()]
            elif op == "neq":
                linhas = [r for r in linhas if str(r.get(campo, "")) != val]
            elif op == "in":
                opts = val.strip("()").split(",")
                linhas = [r for r in linhas if str(r.get(campo, "")) in opts]
        return linhas

    def select(self, tabela, **p):
        linhas = self._filtra(self.t.setdefault(tabela, []), p)
        return linhas[: int(p.get("limit", 10 ** 6))]

    def insert(self, tabela, linhas, upsert=None):
        linhas = linhas if isinstance(linhas, list) else [linhas]
        out = []
        for r in linhas:
            self.ids[tabela] = self.ids.get(tabela, 0) + 1
            r = {"id": self.ids[tabela], "status": "Em conferência", **r} if tabela == "notas" else {"id": self.ids[tabela], **r}
            self.t.setdefault(tabela, []).append(r)
            out.append(r)
        return out

    def update(self, tabela, valores, **f):
        alvo = self._filtra(self.t.get(tabela, []), f)
        for r in alvo:
            r.update(valores)
        return alvo

    def upload(self, caminho, conteudo, content_type=""):
        self.arquivos[caminho] = conteudo


class FakeGraph:
    def __init__(self, pasta):
        self.pasta, self.movidos, self.enviados = pasta, [], []

    def mensagens_novas(self, limite=50):
        msgs = []
        for arq in sorted(self.pasta.glob("demo-*.json")):
            d = json.loads(arq.read_text(encoding="utf-8"))
            msgs.append(Mensagem(d["id"], d["remetente"], d["assunto"], d["recebido_em"], d["corpo"], "", bool(d["anexos"]),
                                 [Anexo(a, "application/pdf", False) for a in d["anexos"]]))
        return msgs

    def anexos(self, msg):
        for a in msg.anexos:
            a.conteudo = (self.pasta / "anexos" / a.nome).read_bytes()
        return msg.anexos

    def mover_para_processados(self, msg_id):
        self.movidos.append(msg_id)

    def enviar(self, para, assunto, html):
        self.enviados.append((para, assunto, html))


def test_robo_ponta_a_ponta(tmp_path):
    import demo_dados
    demo_dados.DEMO, demo_dados.ANEXOS = tmp_path, tmp_path / "anexos"
    demo_dados.main()

    sb = FakeSupabase({
        "filiais": [{"cnpj": "03987645000310", "empresa": "AXT", "filial": "2"},
                    {"cnpj": "05828732000198", "empresa": "VMT", "filial": "1"},
                    {"cnpj": "05828732006552", "empresa": "VMT", "filial": "99"},
                    {"cnpj": "64817850000160", "empresa": "LUNA", "filial": "1"}],
        "fornecedores": [{"cnpj": "53113791000122", "apelido": "TOTVS", "razao": "TOTVS S.A.", "codigos": {"AXT": "10DS6V"}},
                         {"cnpj": "02558157000162", "apelido": "VIVO", "razao": "Telefonica", "codigos": {"*": "01ONA7"}},
                         {"cnpj": "53260240000191", "apelido": "ERPWORKS", "razao": "TMSIGA", "codigos": {"VMT": "ZERDG2"}}],
        "historico": [
            {"id": 1, "prestador": "TOTVS", "empresa": "AXT", "descricao": "SUPORTE PRIME MONITOR ENTERPRISE", "despesa": "OPEX",
             "produto": "S_1.07", "cc": "1810", "conta_contabil": "30110010030", "fornecedor": "10DS6V", "filial": "2", "data_ref": "2026-10-01", "nfs": "1"},
            {"id": 2, "prestador": "ERPWORKS", "empresa": "VMT", "descricao": "DESENV. SISTEMAS - Projeto Implementação do PDV",
             "despesa": "CAPEX", "produto": "S_1.01", "cc": "9915", "conta_contabil": "141104", "fornecedor": "ZERDG2", "filial": "99", "data_ref": "2026-10-01", "nfs": "2"}],
        "perfis": [{"email": "rbastos@commcenter.com.br", "papel": "aprovador"}],
    })
    g = FakeGraph(tmp_path)
    robo = Robo(sb, g)
    r = robo.verificar_caixa()
    assert r == {"emails": 5, "notas": 4, "ignorados": 1, "erros": 0}
    notas = {n["prestador"]: n for n in sb.t["notas"]}
    t = notas["TOTVS"]
    assert (t["empresa"], t["filial"], t["fornecedor"], t["cc"], t["valor"], t["vencimento"]) == ("AXT", "2", "10DS6V", "1810", 12500.0, "2026-11-20")
    assert (notas["VIVO"]["empresa"], notas["VIVO"]["fornecedor"], notas["VIVO"]["tipo_doc"]) == ("VMT", "01ONA7", "FT")
    e = notas["ERPWORKS"]
    assert (e["despesa"], e["conta_contabil"], e["filial"]) == ("CAPEX", "141104", "99")
    assert any("sem cadastro" in a for a in notas["NOVATECH"]["alertas"])
    assert all("_fornecedor_cadastrado" not in n for n in sb.t["notas"])
    assert len([d for d in sb.t["documentos"] if d["nota_id"] == t["id"]]) == 3
    assert len(sb.arquivos) == 8 and len(g.movidos) == 4

    # segunda rodada não duplica
    assert robo.verificar_caixa()["emails"] == 0

    # aviso ao aprovador
    sb.update("notas", {"status": "Aguardando aprovação", "notificado": False}, id=f"eq.{t['id']}")
    assert robo.avisar_aprovador() == 1
    assert g.enviados[0][0] == ["rbastos@commcenter.com.br"] and "TOTVS" in g.enviados[0][2]
    assert robo.avisar_aprovador() == 0
