# Deploy — Nossos Eventos (IF Eventos)

Guia de implantação da aplicação em **produção** (`https://ifeventos.lucianovilasboas.com.br`).

## Visão geral

- **Servidor de produção:** VPS `ovm-1` (`oracle-pm`) — acesso SSH via `ssh ovm-1`.
- **Caminho do repositório no servidor:** `/opt/docker/ifeventos`
- **Stack:** Docker Compose (v2) + Traefik (TLS Let's Encrypt). O público entra pelo
  Traefik em 80/443; o contêiner não publica porta no host.
- **Dentro do contêiner** (porta 8501 = site, 8500 = Socket.IO), o `entrypoint.sh`
  já roda `migrate`, `collectstatic --clear` e `createcachetable` no start — **não**
  é preciso rodar nada disso manualmente.

## Pré-requisitos no servidor

- Docker + Docker Compose v2 instalados.
- Rede externa do Traefik `proxy` criada (`docker network create proxy`).
- `ifeventos/.env` preenchido a partir de `ifeventos/.env.example`.

### Chaves do `.env` (atenção nas novas do ciclo V2.0)

| Chave | Obrigatória | Padrão se ausente |
|---|---|---|
| `OPENAI_API_KEY` | para IA | — (sem chave, IA cai no fallback) |
| `IA_ATIVA` | não | `True` |
| `IA_MODELO_TEXTO` | não | `gpt-4o` |
| `IA_MODELO_CLASSIFICACAO` | não | `gpt-4o-mini` |
| `PROPOSTAS_NOTIFICAR_EMAIL` | não | — |
| `DEBUG` | sim (produção = `False`) | — |

## Deploy (atualizar para a versão mais recente)

No servidor, dentro do repositório:

```bash
cd /opt/docker/ifeventos

# 1. Garantir que está na branch de produção e atualizar
git fetch --tags
git checkout main
git pull --ff-only origin main

# 2. Conferir a versão que vai subir
git describe --tags        # deve mostrar a tag (ex.: v2.0.0)

# 3. (recomendado) backup do banco ANTES de rodar as migrações
#    (fora do repo, para não poluir o git status)
mkdir -p /opt/docker/backups/ifeventos
docker compose exec -T db pg_dump -U django_user django_db \
  > /opt/docker/backups/ifeventos/backup_$(date +%F-%H%M)-pre-$(git describe --tags).sql

# 4. Build e subida (breve indisponibilidade durante o rebuild)
docker compose up -d --build

# 5. Acompanhar o start (migrate -> collectstatic -> gunicorn)
docker compose logs --tail=120 -f app
```

## Logs do deploy (rastreabilidade)

O script `/opt/docker/ifeventos-deploy.sh` (e qualquer execução manual que redirecione a
saída) grava os logs em **`/opt/docker/logs/ifeventos/`** — fora do repositório. Cada rodada
gera `deploy-<AAAA-MM-DD-HHMMSS>.log` com tudo (saída e erros), o **commit antes/depois** e o
status final; o atalho `deploy-latest.log` aponta para a última execução.

```bash
ls -lt /opt/docker/logs/ifeventos/                        # execucoes (mais recente no topo)
tail -n 60 /opt/docker/logs/ifeventos/deploy-latest.log   # ultima execucao
```

## Validação pós-deploy

```bash
docker compose ps                      # app e db "Up"
curl -I https://ifeventos.lucianovilasboas.com.br
```

- O rodapé do site e o admin devem mostrar a versão (`v2.0.0`).
- No admin → **Contextos de IA**, conferir os contextos criados pela migration de seed.
- Funcionalidades novas (relatórios por participante/turma/tipo, "criar gráfico com IA",
  minhas palestras etc.) funcionando na área do organizador.

## Rollback

Volta para o estado anterior à versão atual (ex.: antes da V2.0, `d4f5873`):

```bash
cd /opt/docker/ifeventos
git checkout <commit-ou-tag-anterior>
docker compose up -d --build
```

Migrações aplicadas não são desfeitas automaticamente; as tabelas novas são
ignoradas pelo código antigo (sem quebra). Para reverter migrações, restaurar o
dump feito no passo 3 do deploy.

## Operações úteis

```bash
docker compose logs -f app                      # logs em tempo real
docker compose exec app python manage.py migrate # migrar manualmente (se preciso)
docker compose exec app python manage.py createsuperuser
docker compose exec -T db pg_dump -U django_user django_db > /opt/docker/backups/ifeventos/backup.sql
docker compose exec -T db psql -U django_user -d django_db < /opt/docker/backups/ifeventos/backup.sql
```

### Limpeza de arquivos de certificado (opcional)

Os arquivos de mídia (`media/`) **não** vão pelo git, então modelos `.docx` e
imagens de fundo antigos podem ficar órfãos em cada ambiente. Depois de aplicar
as migrações, remova os que não são usados por nenhuma configuração:

```bash
docker compose exec app python manage.py limpar_arquivos_certificado             # só lista
docker compose exec app python manage.py limpar_arquivos_certificado --confirmar # apaga
```