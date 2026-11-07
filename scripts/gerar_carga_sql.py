"""Gera o SQL de carga inicial (filiais, fornecedores e histórico) a partir da planilha atual.

    python scripts/gerar_carga_sql.py "Notas CLAUDE.xlsx" > carga_inicial.sql

Cole o arquivo gerado no SQL Editor do Supabase e rode. NÃO versionar o .sql (tem dados reais).
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).parent))
from ler_planilha import ler_historico, ler_infos  # noqa: E402


def q(v) -> str:
    if v is None or v == "":
        return "null"
    return "'" + str(v).replace("'", "''") + "'"


def main(caminho: str) -> None:
    wb = openpyxl.load_workbook(caminho, data_only=True, read_only=True)
    filiais, fornecedores = ler_infos(wb)
    historico = ler_historico(wb)
    por_codigo = defaultdict(list)
    for h in historico:
        if h["fornecedor"]:
            por_codigo[h["fornecedor"]].append(h)
    for f in fornecedores.values():
        usos = [h for c in f["codigos"].values() for h in por_codigo.get(c, [])]
        if usos:
            f["apelido"] = max(usos, key=lambda h: h["data_ref"])["prestador"]
        for h in sorted(usos, key=lambda h: h["data_ref"]):
            if h["empresa"]:
                f["codigos"].setdefault(h["empresa"], h["fornecedor"])

    out = ["-- Carga inicial gerada da planilha. Pode rodar mais de uma vez (substitui os dados da planilha).",
           "begin;"]
    for f in filiais:
        out.append(f"insert into public.filiais (cnpj, empresa, filial) values ({q(f['cnpj'])}, {q(f['empresa'])}, {q(f['filial'])}) "
                   "on conflict (cnpj) do update set empresa = excluded.empresa, filial = excluded.filial;")
    for f in fornecedores.values():
        out.append(f"insert into public.fornecedores (cnpj, apelido, razao, codigos) values ({q(f['cnpj'])}, {q(f['apelido'])}, "
                   f"{q(f['razao'])}, {q(json.dumps(f['codigos'], ensure_ascii=False))}::jsonb) "
                   "on conflict (cnpj) do update set apelido = excluded.apelido, razao = excluded.razao, codigos = excluded.codigos;")
    out.append("delete from public.historico where origem like 'planilha%';")
    for h in historico:
        try:
            valor = f"{float(h['valor']):.2f}" if h["valor"] else "null"
        except ValueError:
            valor = "null"
        out.append("insert into public.historico (data_ref, origem, despesa, empresa, prestador, descricao, filial, produto, cc, "
                   f"conta_contabil, fornecedor, valor, nfs) values ({q(h['data_ref'])}, {q('planilha:' + h['aba'])}, {q(h['despesa'])}, "
                   f"{q(h['empresa'])}, {q(h['prestador'])}, {q(h['descricao'])}, {q(h['filial'])}, {q(h['produto'])}, {q(h['cc'])}, "
                   f"{q(h['conta_contabil'])}, {q(h['fornecedor'])}, {valor}, {q(h['nfs'])});")
    out.append("commit;")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1])
