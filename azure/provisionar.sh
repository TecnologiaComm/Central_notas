#!/usr/bin/env bash
# Cria a Central de Notas no Azure App Service (Linux, Python) — rodar UMA vez, no Azure Cloud Shell
# (portal.azure.com > ícone ">_") ou com a Azure CLI logada numa conta com permissão na assinatura.
#
#   bash azure/provisionar.sh
#
# Depois: preencher os segredos (passo 4 do README, "Publicar no Azure") e ligar o GitHub Actions.
set -euo pipefail

# ---------- ajuste aqui ----------
ASSINATURA="${ASSINATURA:-}"                      # vazio = assinatura padrão da CLI
GRUPO="${GRUPO:-rg-central-notas}"
REGIAO="${REGIAO:-brazilsouth}"
PLANO="${PLANO:-plan-central-notas}"
SKU="${SKU:-B1}"                                  # Basic B1 (Always On disponível)
APP="${APP:-central-notas-comm}"                  # vira https://<APP>.azurewebsites.net (nome único no Azure)
TENANT_ID="${TENANT_ID:?informe TENANT_ID=<id do tenant Microsoft 365>}"
CLIENT_ID="${CLIENT_ID:?informe CLIENT_ID=<id do registro de app 'Central de Notas'>}"
# ----------------------------------

[ -n "$ASSINATURA" ] && az account set --subscription "$ASSINATURA"

echo ">> Grupo de recursos e plano"
az group create -n "$GRUPO" -l "$REGIAO" -o none
az appservice plan create -g "$GRUPO" -n "$PLANO" --is-linux --sku "$SKU" -o none

echo ">> App Service (Python 3.12)"
az webapp create -g "$GRUPO" -p "$PLANO" -n "$APP" --runtime "PYTHON:3.12" -o none
az webapp config set -g "$GRUPO" -n "$APP" -o none \
  --startup-file "sh startup.sh" --always-on true --http20-enabled true --min-tls-version 1.2 --ftps-state Disabled
az webapp update -g "$GRUPO" -n "$APP" --https-only true -o none
az webapp config set -g "$GRUPO" -n "$APP" -o none --generic-configurations '{"healthCheckPath": "/saude"}'

echo ">> Configurações (segredos ficam para o passo seguinte)"
URL="https://$APP.azurewebsites.net"
az webapp config appsettings set -g "$GRUPO" -n "$APP" -o none --settings \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  PASTA_DADOS=/home/data \
  URL_BASE="$URL" \
  LOGIN_OBRIGATORIO=true \
  GRAPH_TENANT_ID="$TENANT_ID" \
  GRAPH_CLIENT_ID="$CLIENT_ID" \
  CAIXA_NOTAS=prestacaocontasti@commcenter.com.br \
  SEGREDO_APP="$(openssl rand -hex 32)" \
  TZ=America/Sao_Paulo

echo ">> Login Microsoft (Easy Auth). O app decide quais rotas exigem login (/saude fica aberta)."
az webapp auth update -g "$GRUPO" -n "$APP" -o none \
  --enabled true --unauthenticated-client-action AllowAnonymous --redirect-provider azureactivedirectory
az webapp auth microsoft update -g "$GRUPO" -n "$APP" -o none --yes \
  --client-id "$CLIENT_ID" --client-secret-setting-name MICROSOFT_PROVIDER_AUTHENTICATION_SECRET --issuer "https://login.microsoftonline.com/$TENANT_ID/v2.0" \
  --allowed-audiences "api://$CLIENT_ID" "$CLIENT_ID"

cat <<FIM

Pronto: $URL

Falta (ver README, "Publicar no Azure"):
  1. No registro de app: URI de redirecionamento Web = $URL/.auth/login/aad/callback
     e "Tokens de ID" marcado (Autenticação).
  2. Segredos do app:
       az webapp config appsettings set -g $GRUPO -n $APP --settings GRAPH_CLIENT_SECRET=<segredo> MICROSOFT_PROVIDER_AUTHENTICATION_SECRET=<segredo>
     e as opcionais (SHAREPOINT_SITE, USUARIOS_PERMITIDOS, ANTHROPIC_API_KEY, PROTHEUS_*).
  3. GitHub Actions: baixar o perfil de publicação
       az webapp deployment list-publishing-profiles -g $GRUPO -n $APP --xml
     e salvar como segredo AZURE_WEBAPP_PUBLISH_PROFILE; criar a variável AZURE_WEBAPP_NAME=$APP.
     (Se o download for bloqueado: az resource update -g $GRUPO --namespace Microsoft.Web --resource-type basicPublishingCredentialsPolicies --parent sites/$APP -n scm --set properties.allow=true)
FIM
