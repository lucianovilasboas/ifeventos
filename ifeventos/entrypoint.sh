#!/bin/bash
# =====================================================================
# Nossos Eventos (IF Eventos) — ponto de entrada do contêiner
# ---------------------------------------------------------------------
# Sobe dois processos no mesmo contêiner:
#   8500 -> servidor Socket.IO (ASGI, uvicorn)
#   8501 -> aplicação Django (WSGI)
#
# Variáveis de ambiente reconhecidas:
#   APP_SERVER=gunicorn|runserver   (padrão: gunicorn)
#   APP_WORKERS=<n>                 (padrão: 3)
#   RELOAD=1                        recarrega ao alterar arquivo (só dev)
#   SKIP_MIGRATE=1                  não roda migrações ao iniciar
# =====================================================================
set -e

APP_SERVER="${APP_SERVER:-gunicorn}"
APP_WORKERS="${APP_WORKERS:-3}"
RELOAD="${RELOAD:-0}"

echo "[entrypoint] APP_SERVER=${APP_SERVER} APP_WORKERS=${APP_WORKERS} RELOAD=${RELOAD}"

# ---------------------------------------------------------------------
# 1. Migrações do banco
#    Idempotente: não faz nada se o esquema já estiver aplicado.
# ---------------------------------------------------------------------
if [ "${SKIP_MIGRATE:-0}" != "1" ]; then
    echo "[entrypoint] aplicando migrações..."
    python manage.py migrate --noinput
else
    echo "[entrypoint] migrações ignoradas (SKIP_MIGRATE=1)"
fi

# ---------------------------------------------------------------------
# 2. Arquivos estáticos
#    Necessário em produção: com DEBUG=False o Django não os serve sozinho.
#    O WhiteNoise passa a servi-los a partir de STATIC_ROOT.
# ---------------------------------------------------------------------
echo "[entrypoint] coletando arquivos estáticos..."
python manage.py collectstatic --noinput --clear >/dev/null

# ---------------------------------------------------------------------
# 3. Tabela de cache (django.core.cache.backends.db.DatabaseCache)
#    createcachetable é idempotente.
# ---------------------------------------------------------------------
python manage.py createcachetable >/dev/null 2>&1 || true

# ---------------------------------------------------------------------
# 4. Servidor Socket.IO (porta 8500), em segundo plano
# ---------------------------------------------------------------------
if [ "$RELOAD" = "1" ]; then
    uvicorn socket_server:app --host 0.0.0.0 --port 8500 --reload &
else
    uvicorn socket_server:app --host 0.0.0.0 --port 8500 &
fi
SOCKET_PID=$!

# Repassa sinais para o Socket.IO quando o contêiner for parado
trap 'kill -TERM "$SOCKET_PID" 2>/dev/null || true' TERM INT

# ---------------------------------------------------------------------
# 5. Aplicação Django (porta 8501) em primeiro plano
#    O "exec" garante que o processo receba os sinais corretamente.
# ---------------------------------------------------------------------
if [ "$APP_SERVER" = "runserver" ]; then
    echo "[entrypoint] usando o servidor de desenvolvimento (não use exposto na internet)"
    exec python manage.py runserver 0.0.0.0:8501
fi

echo "[entrypoint] iniciando gunicorn com ${APP_WORKERS} workers"
exec gunicorn setup.wsgi:application \
    --bind 0.0.0.0:8501 \
    --workers "$APP_WORKERS" \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
