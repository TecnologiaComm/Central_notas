#!/bin/sh
# Comando de inicialização no Azure App Service (Configuração > Configurações gerais > Comando de inicialização).
# Um processo só: a verificação da caixa a cada 5 min roda dentro do app.
python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
