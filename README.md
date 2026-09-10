# Nossos Eventos — IFMG Campus Ponte Nova

Portal de eventos do campus: divulgação de eventos e atividades, inscrições,
controle de presença por QR code e emissão de certificados.

- **Produção:** https://ifeventos.lucianovilasboas.com.br
- **Painel do organizador:** `/organizador/dashboard/`
- **Painel do participante:** `/participante/dashboard/`
- **API REST:** `/api/v1/` (documentação em `/api/v1/docs/`)
- **Admin do Django:** `/admin/`

## Tecnologias

Django 5.2 · PostgreSQL 15 · Bootstrap 5.3 · django-allauth · DRF +
drf-spectacular · python-socketio (tempo real) · WhiteNoise (arquivos
estáticos) · Gunicorn (WSGI) · Docker + Traefik (TLS Let's Encrypt).

O design segue o design system da repaginação, com o verde institucional do
IFMG (`#2F9E41`, PANTONE 362 C) e o vermelho `#CD191E` (PANTONE 187 C).

## Estrutura

```
.
├── docker-compose.yml        # produção (Traefik, sem portas expostas)
├── docker-compose.dev.yml    # desenvolvimento local (portas 8500/8501)
├── ifeventos/                # aplicação Django
│   ├── entrypoint.sh         # migrações, collectstatic e servidores
│   ├── Dockerfile
│   ├── requirements.txt      # versões fixadas
│   ├── .env.example          # modelo das variáveis (copiar para .env)
│   ├── setup/                # settings e rotas do projeto
│   ├── eventos/              # app principal (eventos, certificados, QR)
│   ├── participante/         # inscrições do participante
│   ├── organizador/          # gestão de eventos e atividades
│   ├── relatorios/           # relatórios e listas de presença
│   ├── api/                  # API REST
│   ├── templates/
│   └── static/
└── postgres_data/            # dados do banco (não versionado)
```

## Implantação no servidor (produção)

Pré-requisitos no servidor: Docker, Docker Compose, e um Traefik em execução
com a rede externa `proxy` e o resolvedor de certificados `letsencrypt`.

```bash
# 1. Clonar
cd /opt/docker
git clone https://github.com/lucianovilasboas/ifeventos.git
cd ifeventos

# 2. Criar o arquivo de segredos (NÃO existe no repositório)
cp ifeventos/.env.example ifeventos/.env
#    edite o .env: SECRET_KEY, DB_PASSWORD, POSTGRES_PASSWORD, OPENAI_API_KEY,
#    e-mail, e confirme DEBUG=False e os domínios.

# 3. Subir
docker compose up -d --build

# 4. Acompanhar
docker compose logs -f app
```

O `entrypoint.sh` roda as migrações, o `collectstatic` e sobe dois processos:
Gunicorn na 8501 (site) e Uvicorn na 8500 (Socket.IO). Nada é publicado
diretamente no host — o acesso público passa pelo Traefik em 80/443.

### Variáveis de ambiente

Todas em `ifeventos/.env`. O modelo comentado está em `ifeventos/.env.example`.

As essenciais:

- `SECRET_KEY` — gere uma nova por ambiente:
  `python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"`
- `DEBUG=False` em produção (com `True` o Django expõe stack traces)
- `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` — sem o segundo, **o login e os
  formulários falham** atrás do proxy TLS
- `DB_*` **e** `POSTGRES_*` — os valores precisam ser idênticos entre si
  (o Django lê `DB_*`, o contêiner do Postgres lê `POSTGRES_*`)
- `SITE_URL` — usado no QR code do certificado
- `SOCKET_URL` — em produção deixe **vazio** (mesma origem, via Traefik)

### Copiar a mídia (imagens dos eventos)

A pasta `ifeventos/media/` não é versionada. Para levar as imagens:

```bash
rsync -avz ifeventos/media/ ovm-1:/opt/docker/ifeventos/ifeventos/media/
```

Ela está montada como volume no contêiner, então os arquivos aparecem
imediatamente, sem rebuild.

## Desenvolvimento local

```bash
docker compose -f docker-compose.dev.yml up -d --build
# http://127.0.0.1:8501/eventos/
```

Neste modo o `.env` precisa de `DEBUG=True`, `ALLOWED_HOSTS=*` e
`SOCKET_URL=http://127.0.0.1:8500` (sem proxy, o navegador conecta direto na
porta do Socket.IO).

## Comandos úteis (dentro do contêiner)

```bash
docker compose exec app python manage.py createsuperuser
docker compose exec app python manage.py migrate
docker compose exec app python manage.py shell

# Backup e restauração do banco
docker compose exec -T db pg_dump -U django_user django_db > backup.sql
docker compose exec -T db psql -U django_user -d django_db < backup.sql
```

## Acesso à API REST

```bash
# Gere um token para um usuário
docker compose exec app python manage.py drf_create_token <usuario>

# Consuma
curl -H "Authorization: Token <token>" https://ifeventos.lucianovilasboas.com.br/api/v1/eventos/
```

## Segurança

- Nenhum segredo é versionado: `.env` está no `.gitignore` e `.dockerignore`.
- O repositório é público apenas com código e configuração de exemplo.
- Os arquivos estáticos são servidos pelo WhiteNoise; em produção `DEBUG=False`.
- Certificado TLS emitido e renovado automaticamente pelo Traefik.

## Manutenção

- **Atualizar o site:** `git pull && docker compose up -d --build`
- **Trocar o domínio:** ajuste as labels `Host(...)` no `docker-compose.yml`,
  além de `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` e `SITE_URL` no `.env`.
- **Logs:** `docker compose logs -f app`
