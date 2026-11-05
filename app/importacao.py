"""Importa a planilha atual do administrativo para o app.

    python scripts/importar_planilha.py "Notas CLAUDE.xlsx"     (grava em config/)
    ou, no app publicado: menu "Carga da planilha"            (grava em <PASTA_DADOS>/config e recarrega)

Gera:
  config/filiais.yaml      <- aba Infos (linhas !FILIAL): CNPJ -> EMPRESA + FILIAL
  config/fornecedores.csv  <- aba Infos: CNPJ -> apelido (PRESTADOR), razão social, código Protheus por empresa
  config/historico.csv     <- todas as abas mensais: base para sugerir DESPESA/PRODUTO/CC/CONTA/FORNECEDOR

Depois de rodar, apague data/notas.db (ou rode com --recarregar) para o app reler os arquivos.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import openpyxl
import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config"
MESES = ["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]

# cabeçalho normalizado -> campo
MAPA = {
    "despesa": "despesa", "empresa": "empresa", "plataforma": "empresa", "axt vmt etc": "empresa",
    "prestador": "prestador", "descricao": "descricao", "filial": "filial",
    "produto": "produto", "produto 1": "produto", "cc": "cc", "cc 2": "cc",
    "conta contabil": "conta_contabil", "conta contabil 3": "conta_contabil",
    "fornecedor": "fornecedor", "fornecedor 4": "fornecedor", "valor": "valor", "pc": "pc", "nfs": "nfs",
    "chamado": "chamado", "status chamado": "status_chamado", "status nota": "status_nota",
    "data chamado": "data_chamado", "vencimento": "vencimento",
}
CAMPOS_HIST = ["data_ref", "aba", "despesa", "empresa", "prestador", "descricao", "filial", "produto", "cc",
               "conta_contabil", "fornecedor", "valor", "pc", "nfs", "chamado", "status_nota", "vencimento"]


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def limpo(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return str(v).replace("\xa0", " ").strip()


def cnpj(v) -> str:
    d = re.sub(r"\D", "", limpo(v))
    return d.zfill(14) if d else ""


def filial_cod(v) -> str:
    v = limpo(v)
    return str(int(v)) if v.isdigit() else v


def ler_infos(wb):
    filiais, fornecedores = [], {}
    ws = wb["Infos"]
    for r in list(ws.iter_rows(values_only=True))[1:]:
        cod_axt, cod_vmt, apelido, nome, c, empresa = (list(r) + [None] * 6)[:6]
        c = cnpj(c)
        if not c:
            continue
        if limpo(apelido) == "!FILIAL":
            partes = limpo(nome).split()
            filiais.append({"empresa": partes[0].upper(),
                            "filial": filial_cod(partes[1]) if len(partes) > 1 else "1", "cnpj": c})
            continue
        f = fornecedores.setdefault(c, {"cnpj": c, "apelido": limpo(apelido).upper(),
                                        "razao": limpo(nome), "codigos": {}})
        codigo = limpo(cod_vmt) or limpo(cod_axt)
        if codigo:
            for emp in (limpo(empresa).upper().split("/") if limpo(empresa) else ["*"]):
                f["codigos"][emp.strip()] = codigo
    return filiais, fornecedores


def ler_historico(wb):
    linhas, ano, mes_ant = [], None, 0
    for ws in wb.worksheets:
        nome = norm(ws.title)
        mes = next((i + 1 for i, m in enumerate(MESES) if nome.startswith(m)), None)
        if not mes:
            continue
        m = re.search(r"(\d{2,4})$", nome)
        if m:
            ano = 2000 + int(m.group(1)) % 100
        else:
            ano = ano or (2025 if mes >= 7 else 2026)
            if mes < mes_ant:
                ano += 1
        mes_ant = mes
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        idx = {}
        for i, h in enumerate(rows[0]):
            campo = MAPA.get(norm(h))
            if campo and campo not in idx:
                idx[campo] = i
        for r in rows[1:]:
            d = {k: limpo(r[i]) if i < len(r) else "" for k, i in idx.items()}
            if not d.get("prestador"):
                continue
            d.update(data_ref=f"{ano}-{mes:02d}-01", aba=ws.title)
            d["empresa"] = d.get("empresa", "").upper()
            d["prestador"] = d["prestador"].upper()
            d["filial"] = filial_cod(d.get("filial"))
            d["produto"] = d.get("produto", "").upper().strip()
            d["despesa"] = d.get("despesa", "").upper()
            if d.get("fornecedor", "").upper() == "XXX":
                d["fornecedor"] = ""
            linhas.append({k: d.get(k, "") for k in CAMPOS_HIST})
    return linhas


def importar(origem, destino: Path = CONFIG) -> dict:
    """origem: caminho ou arquivo aberto (.xlsx). Grava filiais.yaml, fornecedores.csv e historico.csv em destino."""
    wb = openpyxl.load_workbook(origem, data_only=True, read_only=True)
    filiais, fornecedores = ler_infos(wb)
    historico = ler_historico(wb)

    # Apelido = como o PRESTADOR aparece nas abas mais recentes para aquele código de fornecedor
    por_codigo = defaultdict(list)
    for h in historico:
        if h["fornecedor"]:
            por_codigo[h["fornecedor"]].append(h)
    for f in fornecedores.values():
        usos = [h for c in f["codigos"].values() for h in por_codigo.get(c, [])]
        if usos:
            f["apelido"] = max(usos, key=lambda h: h["data_ref"])["prestador"]
        # completa os códigos por empresa com o que foi usado no histórico
        for h in sorted(usos, key=lambda h: h["data_ref"]):
            if h["empresa"]:
                f["codigos"].setdefault(h["empresa"], h["fornecedor"])

    destino.mkdir(parents=True, exist_ok=True)
    with (destino / "filiais.yaml").open("w", encoding="utf-8") as fh:
        fh.write("# Gerado a partir da aba 'Infos' da planilha. CNPJ do tomador -> EMPRESA (sigla) + FILIAL (código Protheus)\n")
        yaml.safe_dump({"filiais": filiais}, fh, allow_unicode=True, sort_keys=False)
    with (destino / "fornecedores.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["cnpj", "apelido", "razao", "codigos"])
        for f in sorted(fornecedores.values(), key=lambda x: x["apelido"]):
            w.writerow([f["cnpj"], f["apelido"], f["razao"],
                        "|".join(f"{k}={v}" for k, v in f["codigos"].items())])
    with (destino / "historico.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS_HIST, delimiter=";")
        w.writeheader()
        w.writerows(historico)
    return {"filiais": len(filiais), "fornecedores": len(fornecedores), "historico": len(historico)}
