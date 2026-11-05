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
[NF lançada] ── quando o status da nota vira "NF LANÇADA"
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
No app publicado, use o menu **Carga da planilha**. Localmente:
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
| `app/sharepoint.py` | Cópia dos arquivos renomeados e da planilha numa biblioteca do SharePoint (Graph) |
| `app/auth.py` | Login Microsoft (Easy Auth do App Service) e lista de usuários permitidos |
| `app/importacao.py` | Carga da planilha atual (aba Infos + abas mensais), pela tela ou pelo script |
| `app/ingest.py` | Lê a caixa, agrupa os anexos por nota, preenche os campos e gera os alertas |
| `app/sugestao.py` | Sugestões com base no histórico |
| `app/classify.py` / `app/extract.py` | Classificação e leitura de XML, PDF e linha digitável |
| `app/naming.py` / `app/conferencia.py` | Nomenclatura, pastas, salvar conferência/lançamento e memorizar |
| `app/aprovacao.py` | E-mail de "de acordo", links assinados e leitura das respostas |
| `app/planilha.py` | Exportação no layout das abas mensais |
| `azure/provisionar.sh`, `startup.sh`, `.github/workflows/azure.yml` | Criação do App Service, inicialização e publicação automática |
| `config/` | Filiais, fornecedores, histórico, regra de aprovação (`aprovacao.yaml`: Robson) |

## Testar sem credenciais (modo demo)
```bash
pip install -r requirements.txt
python scripts/gerar_demo.py          # 5 e-mails de exemplo: TOTVS (XML+DANFE+boleto), VIVO, ERPWORKS, fornecedor novo, newsletter
echo MODO_DEMO=true > .env
uvicorn app.main:app --port 8000       # http://localhost:8000 → "Verificar e-mails agora"
pytest -q
```
No modo demo, os e-mails "enviados" ficam em `data/demo_enviados/`.

## Publicar no Azure (recomendado)
O app roda no **Azure App Service**, no mesmo tenant do Microsoft 365: vira um site com login da conta da Comm,
acessível de qualquer lugar (inclusive celular, sem VPN), e cada alteração na `main` do GitHub é publicada sozinha.

```
GitHub (TecnologiaComm/Central_notas) ── push na main ──▶ GitHub Actions: testes ──▶ publica
                                                                                     │
Azure App Service (Linux, Python, B1 com Always On) ◀─────────────────────────────────┘
  https://central-notas-comm.azurewebsites.net   (login Microsoft – Entra ID)
   ├── Microsoft Graph: lê/envia e-mails da prestacaocontasti@
   ├── Microsoft Graph: copia os arquivos renomeados e a planilha para o SharePoint
   └── /home/data: banco (SQLite) + cópia de trabalho dos arquivos (disco persistente do App Service)
```

### 1. Registro do app no Microsoft Entra ID (admin do M365) — o mesmo para Outlook, SharePoint e login
1. **Registros de aplicativo → Novo registro**: nome "Central de Notas", contas **somente deste diretório**.
2. **Permissões de API → Microsoft Graph → Permissões de aplicativo**: `Mail.ReadWrite`, `Mail.Send` e `Sites.Selected`
   → **Conceder consentimento do administrador**.
3. **Certificados e segredos**: criar um segredo do cliente (anote o valor).
4. **Autenticação**: plataforma **Web** com URI `https://<APP>.azurewebsites.net/.auth/login/aad/callback` e **Tokens de ID** marcado.
5. Restringir a caixa (Exchange Online PowerShell):
   ```powershell
   New-DistributionGroup -Name "App Central de Notas" -Type Security -Members prestacaocontasti@commcenter.com.br
   New-ApplicationAccessPolicy -AppId <CLIENT_ID> -PolicyScopeGroupId "App Central de Notas" `
       -AccessRight RestrictAccess -Description "Central de Notas so acessa prestacaocontasti"
   ```
6. Liberar a escrita **só no site das notas** (`Sites.Selected`), com o Microsoft Graph PowerShell:
   ```powershell
   Connect-MgGraph -Scopes "Sites.FullControl.All"
   $site = Get-MgSite -SiteId "commcenter.sharepoint.com:/sites/PrestacaodeContasTI"
   New-MgSitePermission -SiteId $site.Id -BodyParameter @{ roles = @("write");
     grantedToIdentities = @(@{ application = @{ id = "<CLIENT_ID>"; displayName = "Central de Notas" } }) }
   ```
7. Opcional, para limitar quem entra: **Aplicativos empresariais → Central de Notas → Propriedades → Atribuição necessária = Sim**
   e adicionar o time e o Robson em **Usuários e grupos** (ou usar `USUARIOS_PERMITIDOS`, abaixo).

### 2. Criar os recursos no Azure (uma vez)
No **Azure Cloud Shell** (portal.azure.com → ícone `>_`), com o repositório clonado:
```bash
TENANT_ID=<id do tenant> CLIENT_ID=<id do registro de app> APP=central-notas-comm bash azure/provisionar.sh
```
O script cria o grupo de recursos, o plano **B1 Linux** com **Always On** (necessário para a verificação a cada 5 min),
o App Service Python 3.12, a verificação de saúde em `/saude`, HTTPS obrigatório, `PASTA_DADOS=/home/data` e o login Microsoft.

### 3. Segredos e opções (App Service → Configuração → Configurações de aplicativo)
| Configuração | Valor |
|---|---|
| `GRAPH_CLIENT_SECRET` e `MICROSOFT_PROVIDER_AUTHENTICATION_SECRET` | o segredo do passo 1.3 |
| `SHAREPOINT_SITE` | `commcenter.sharepoint.com:/sites/PrestacaodeContasTI` (vazio = não copia para o SharePoint) |
| `SHAREPOINT_BIBLIOTECA` / `SHAREPOINT_PASTA` | biblioteca e pasta raiz (padrão `Documentos` / `Notas`) |
| `USUARIOS_PERMITIDOS` | opcional: `renan@commcenter.com.br, @financeiro.commcenter.com.br` (o aprovador sempre abre o próprio link) |
| `ANTHROPIC_API_KEY` | opcional: leitura por IA de PDFs sem XML |

### 4. Publicação automática pelo GitHub
1. Baixar o perfil de publicação: App Service → **Visão geral → Baixar perfil de publicação**
   (ou `az webapp deployment list-publishing-profiles -g rg-central-notas -n <APP> --xml`).
2. No GitHub, **Settings → Secrets and variables → Actions**: segredo `AZURE_WEBAPP_PUBLISH_PROFILE` (conteúdo do arquivo)
   e variável `AZURE_WEBAPP_NAME` = `<APP>`.
3. A cada push na `main`, `.github/workflows/azure.yml` roda os testes e publica. Pull requests só rodam os testes.

### 5. Carga inicial e primeiro uso
1. Abrir `https://<APP>.azurewebsites.net`, entrar com a conta da Comm.
2. **Carga da planilha**: enviar a planilha atual (aba Infos + abas mensais). Filiais, fornecedores e histórico
   ficam em `/home/data/config` e não se perdem nas publicações.
3. **Verificar e-mails agora** e conferir as primeiras notas.

### Como fica cada coisa
- **Login**: conta Microsoft da Comm (Easy Auth do App Service). O nome que aparece no histórico e na planilha é o
  e-mail de quem conferiu/aprovou — não dá mais para digitar outro nome.
- **Arquivos**: renomeados na cópia de trabalho (`/home/data/arquivos`) e enviados para
  `<biblioteca>/<SHAREPOINT_PASTA>/<EMPRESA>/<AAAA-MM>/` quando a nota sai da conferência. A nota mostra os links do
  SharePoint. Se o envio falhar, ele é refeito na próxima verificação; a planilha `CONTROLE_NOTAS.xlsx` também é
  atualizada lá a cada verificação.
- **Banco**: SQLite em `/home/data/notas.db` (disco persistente). Rode **uma instância só** (não ligar escala horizontal),
  porque o agendador roda dentro do app. Para Azure SQL/PostgreSQL, use `DATABASE_URL` (e inclua o driver no `requirements.txt`).
- **Backup**: App Service → **Backups** (plano B1 ou superior) cobre `/home`.

### Alternativa: servidor interno
- `.env` a partir do `.env.example` (com `PASTA_ARQUIVOS` apontando para o compartilhamento de rede).
- **Windows Server:** [NSSM](https://nssm.cc) com `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`;
  **Linux:** systemd com o mesmo comando. Um processo só.
- IIS/nginx na frente com HTTPS e autenticação, repassando o usuário em `X-Remote-User`.

### Observações
- Os links são assinados por aprovador, e a decisão só é registrada no clique de confirmação. Assim, o Safe Links do Outlook não aprova sozinho ao verificar o link.
- O Robson também pode responder o e-mail com "De acordo".
- O `sendMail` do Graph aceita anexos de até ~3 MB cada.

## Próximos passos
1. Rodar alguns dias lendo a caixa real, só conferindo, sem pedir de acordo.
2. O lançamento no Protheus continua manual: depois do "de acordo", o analista lança e preenche PC, chamado e status no app.
