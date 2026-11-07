# Central de Notas – Prestação de Contas TI (Comm)

Versão 1: tudo no **GitHub** + **Supabase**, sem servidor.

| Peça | Onde roda | O que faz |
|---|---|---|
| Site (`docs/`) | GitHub Pages | Login, fila, conferência, de acordo do Robson, lançamento, exportar planilha |
| Robô (`worker/`) | GitHub Actions, a cada 15 min (seg–sex, 8h–19h45) | Lê a caixa `prestacaocontasti@`, cria as notas pré-preenchidas, avisa o aprovador por e-mail |
| Banco, login e arquivos | Supabase | Tabelas, usuários, e os PDFs/XML no bucket privado `notas` |

Só usuários cadastrados no Supabase entram (cadastro aberto desligado). Analistas conferem e pedem o de acordo; só o **aprovador** (Robson) ou o admin registram De acordo / Não de acordo — regra garantida no banco.

## Fluxo
1. O robô lê o e-mail, classifica os anexos (NF, FT, XML, boleto, memória), lê os dados e sugere empresa/filial, prestador, código do fornecedor, despesa, produto, CC e conta pelo histórico da planilha.
2. O analista confere e clica em **Salvar e pedir "de acordo"**: os arquivos são renomeados para `PRESTADOR_NFouFT_NÚMERO_EMPRESA` (+ `_BOLETO`, `_MC`) em `<EMPRESA>/<AAAA-MM>/`.
3. O robô avisa o Robson por e-mail; ele entra no site e dá o de acordo.
4. O analista lança no Protheus e preenche PC, chamado e status. Com "NF LANÇADA" a nota sai da fila.
5. **Baixar planilha** gera o Excel com uma aba por mês nas 17 colunas atuais.

## Implantação
Passo a passo completo no documento "Central de Notas – Passo a passo de implantação". Resumo:

1. **Supabase:** criar o projeto → SQL Editor → rodar `supabase/schema.sql` e depois `carga_inicial.sql` (gerado da planilha, não fica no repositório) → Authentication: desligar *Allow new users to sign up* e criar os 5 usuários → rodar `supabase/usuarios.sql`.
2. **Microsoft 365:** registrar o app no Entra ID (Mail.ReadWrite e Mail.Send de aplicativo) restrito à caixa `prestacaocontasti@`.
3. **GitHub:** preencher `docs/config.js` (URL + anon key) · Settings → Secrets → Actions: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET` · Settings → Pages: branch `main`, pasta `/docs`.
4. Actions → **Robô da caixa** → *Run workflow* para o primeiro teste.

## Desenvolvimento
```bash
pip install -r requirements-dev.txt
pytest -q
python scripts/gerar_carga_sql.py "Notas CLAUDE.xlsx" > carga_inicial.sql
```
