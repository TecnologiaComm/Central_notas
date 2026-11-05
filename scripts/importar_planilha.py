"""Importa a planilha atual do administrativo (aba Infos + abas mensais) para config/.

    python scripts/importar_planilha.py "Notas CLAUDE.xlsx"

Depois apague data/notas.db para o app reler os arquivos. No app publicado, use o menu "Carga da planilha".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.importacao import importar  # noqa: E402

if __name__ == "__main__":
    r = importar(sys.argv[1])
    print(f"{r['filiais']} filiais, {r['fornecedores']} fornecedores, {r['historico']} linhas de histórico importadas.")
