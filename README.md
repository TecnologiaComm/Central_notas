# Central de Notas – Comm (Prestação de Contas TI)

App interno que lê a caixa **prestacaocontasti@commcenter.com.br**, separa os anexos (NF, FT, XML, boleto e memória de cálculo), renomeia os arquivos no padrão do time e pré-preenche a linha da planilha. Ele também já sugere DESPESA, PRODUTO, CC, conta contábil e o código do fornecedor com base no histórico, pede o "de acordo" ao Robson e controla PC, chamado e status até a NF ser lançada.

## Fluxo

```
Outlook (prestacaocontasti@)
   │  a cada 5 min (ou botão "Verificar e-mails agora")
   ▼
Ingestão ── classifica anexos e lê os dados (XML NF-e/NFS-e > IA opcional > PDF)
   │        EMPRESA + FILIAL ........ pelo CNPJ do tomador (aba Infos)
   │        PRESTADOR + FORNECEDOR .. pelo CNPJ do prestador (aba Infos: código Protheus por empresa)
   │        DESPESA/PRODUTO/CC/CONTA  pelo histórico: linha mais parecida do mesmo prestador/empresa
   ▼
[Em conferência] ── analista confere → "Salvar e pedir de acordo"
   │        arquivos: PRESTADOR_NFouFT_NÚMERO_EMPRESA(.pdf | _BOLETO | _MC) em <EMPRESA>/<AAAA-MM>/
   │        status chamado = SUSPENSO - APROV
   ▼
[Aguardando aprovação] ── e-mail para rbastos@ com botões De acordo / Não de acordo
   │        (ou o Robson responde "De acordo" no próprio e-mail)
   ▼
[Aprovada] ── analista lança no Protheus e preenche PC, chamado, status chamado/nota e data
   ▼
[NF lançada] ── botão "Lançar no Protheus" (MATA103 via REST) ou status "NF LANÇADA" preenchido à mão
```

## A planilha
- **Baixar planilha** gera um arquivo com **uma aba por mês** ("Novembro 26"…) com as mesmas 17 colunas das abas atuais: DESPESA, EMPRESA, PRESTADOR, DESCRIÇÃO, FILIAL, PRODUTO, CC, CONTA CONTABIL, FORNECEDOR, VALOR, PC, NFS, CHAMADO, STATUS CHAMADO, STATUS NOTA, DATA CHAMADO e VENCIMENTO.
- A aba **Controle app** traz a etapa de cada nota, quem deu o de acordo, quando, e em que pasta estão os arquivos.
- Uma cópia é regravada automaticamente em `<PASTA_ARQUIVOS>/CONTROLE_NOTAS.xlsx` a cada alteração.

## Alertas automáticos
- **Duplicidade:** NFS do mesmo prestador já lançada na planilha antiga ou já existente no app.
- **Fornecedor:** CNPJ novo (sem cadastro) ou sem código Protheus para aquela empresa.
- **Empresa/filial:** não identificada pelo CNPJ do tomador.
- **Prazos e valores:** vencimento em até 3 dias, valor do boleto diferente do valor da nota e campos que não puderam ser lidos.

## Carga a partir da planilha atual
```bash
python scripts/importar_planilha.py "Notas CLAUDE.xlsx"
```
Esse comando gera três arquivos de configuração:
- `config/filiais.yaml`, com 14 filiais (aba Infos);
- `config/fornecedores.csv`, com 27 CNPJs de prestadores e seus códigos por empresa;
- `config/historico.csv`, com cerca de 730 lançamentos de jul/25 a nov/26.

O banco carrega esses arquivos na primeira execução. Para recarregar, apague `data/notas.db`. A cada conferência salva no app, o histórico e o cadastro são atualizados, e as sugestões melhoram com o uso.

## Estrutura
| Arquivo | O que faz |
|---|---|
| `app/graph.py` | Integração com o Outlook via Microsoft Graph, mais um simulador para o modo demo |
| `app/ingest.py` | Lê a caixa, agrupa os anexos por nota, preenche os campos e gera os alertas |
| `app/sugestao.py` | Sugestões com base no histórico |
| `app/classify.py` / `app/extract.py` | Classificação e leitura de XML, PDF e linha digitável |
| `app/naming.py` / `app/conferencia.py` | Nomenclatura, pastas, salvar conferência/lançamento e memorizar |
| `app/aprovacao.py` | E-mail de "de acordo", links assinados e leitura das respostas |
| `app/planilha.py` | Exportação no layout das abas mensais |
| `app/protheus.py` | Lançamento da nota aprovada no Protheus via REST (mais um simulador para o modo demo) |
| `protheus/CENTRALNOTAS.tlpp` | Endpoint REST do lado Protheus (MsExecAuto MATA103/MATA140) — compilar no RPO |
| `config/` | Filiais, fornecedores, histórico, regra de aprovação (`aprovacao.yaml`: Robson) e mapeamento do Protheus (`protheus.yaml`) |

## Testar sem credenciais (modo demo)
```bash
pip install -r requirements.txt
python scripts/gerar_demo.py          # 5 e-mails de exemplo: TOTVS (XML+DANFE+boleto), VIVO, ERPWORKS, fornecedor novo, newsletter
echo MODO_DEMO=true > .env
uvicorn app.main:app --port 8000       # http://localhost:8000 → "Verificar e-mails agora"
pytest -q
```
No modo demo, os e-mails "enviados" ficam em `data/demo_enviados/` e os lançamentos simulados no Protheus em `data/demo_protheus/`.

## Colocar em produção (servidor interno)

### 1. Registrar o app no Microsoft Entra ID (admin do M365)
1. Abrir **Registros de aplicativo → Novo registro**, com o nome "Central de Notas".
2. Em **Permissões de API → Microsoft Graph → Permissões de aplicativo**, adicionar `Mail.ReadWrite` e `Mail.Send` e clicar em **Conceder consentimento do administrador**.
3. Criar um **segredo do cliente**.
4. Restringir o app só à caixa da prestação de contas:
   ```powershell
   New-DistributionGroup -Name "App Central de Notas" -Type Security -Members prestacaocontasti@commcenter.com.br
   New-ApplicationAccessPolicy -AppId <CLIENT_ID> -PolicyScopeGroupId "App Central de Notas" `
       -AccessRight RestrictAccess -Description "Central de Notas so acessa prestacaocontasti"
   ```

### 2. Configurar
- Copiar `.env.example` para `.env` e preencher o tenant, o client id, o segredo, `URL_BASE` e `SEGREDO_APP`.
- Em `PASTA_ARQUIVOS`, apontar para o compartilhamento de rede onde as notas são guardadas hoje.
- Opcional: `ANTHROPIC_API_KEY` para ler com mais precisão os PDFs que chegam sem XML.

### 3. Rodar como serviço
- **Windows Server:** usar o [NSSM](https://nssm.cc) com `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`.
- **Linux:** usar o systemd com o mesmo comando.
- Rodar **um processo só**, porque o agendador da verificação roda dentro do app.
- Recomendado: IIS ou nginx na frente, com HTTPS e autenticação Windows/Entra, repassando o usuário em `X-Remote-User`.

### Observações
- Os botões de "de acordo" abrem na rede interna ou na VPN. Fora dela, o Robson pode responder o e-mail com "De acordo".
- Os links são assinados por aprovador, e a decisão só é registrada no clique de confirmação. Assim, o Safe Links do Outlook não aprova sozinho ao verificar o link.
- O `sendMail` do Graph aceita anexos de até ~3 MB cada.
- O banco padrão é SQLite. Para SQL Server, use `DATABASE_URL=mssql+pyodbc://...`.

## Integração com o Protheus (fase 2)
Depois do "de acordo", a nota pode ser lançada no Protheus direto pelo app.

```
app (nota aprovada) ──POST JSON──▶ /rest/centralnotas/v1/documento-entrada  (cabeçalho tenantId: grupo,filial)
                                    └─ CENTRALNOTAS.tlpp → MsExecAuto MATA103 (ou MATA140) → SF1/SD1/SE2
                     ◀── {documento, série, recno, pedidoCompra} ── grava "Doc. Protheus", PC e status "NF LANÇADA"
```

1. **Lado Protheus (TI/consultoria TOTVS):** compilar `protheus/CENTRALNOTAS.tlpp` no RPO, publicar no serviço REST do AppServer
   e criar um usuário de integração com acesso ao MATA103/MATA140. Validar TES, condição de pagamento, natureza e retenções.
2. **`config/protheus.yaml`:** rotina (`MATA103` lança direto; `MATA140` gera pré-nota para o fiscal classificar),
   grupo de empresa de cada sigla (VMT, AXT...), tamanho da filial/documento e TES/condição/natureza padrão (também por empresa).
   Loja diferente de `01`: cadastrar o código do fornecedor como `10DS6V/02`.
3. **`.env`:** `PROTHEUS_URL` (ex.: `http://protheus:8181/rest`), `PROTHEUS_AUTH` (`basic` ou `oauth2`), `PROTHEUS_USUARIO`, `PROTHEUS_SENHA`.
   `PROTHEUS_LANCAR_AUTOMATICO=true` lança sozinho as notas aprovadas (a cada verificação e logo após o clique de aprovação).

Comportamento:
- O app valida antes de enviar (empresa, filial, fornecedor, NFS, valor, produto, CC, conta e vencimento).
- O endpoint confere fornecedor/CNPJ na SA2 e é **idempotente**: se o documento já existe na SF1, devolve o existente.
- Com parcela única, o vencimento do título na SE2 é alinhado ao vencimento do boleto.
- Erro do ExecAuto aparece na nota e no histórico; o lançamento automático não insiste até alguém clicar em "Tentar de novo".
- A aba **Controle app** da planilha ganhou a coluna **DOC. PROTHEUS**.

## Próximos passos
1. Rodar alguns dias lendo a caixa real, só conferindo, sem pedir de acordo.
2. Login com conta Microsoft (Entra ID).
3. Homologar o endpoint do Protheus em base de teste com a consultoria TOTVS (rotina, TES, retenções) e depois ligar o lançamento automático.
