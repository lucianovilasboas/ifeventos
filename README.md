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

## Metadados do participante (configurável por escola)

Dados extras do aluno/servidor (matrícula, curso, turma, ano/período, função…)
não ficam em colunas fixas no banco: cada escola os declara em
`settings.METADADOS_PARTICIPANTE`. Os valores são gravados num JSON
(`ParticipanteMetadados.dados`) e aparecem no cadastro/perfil, na lista de
presença e no relatório de inscrições (com seleção de colunas).

Cada item da lista é um dicionário:

| Chave | Obrigatório | Descrição |
|---|---|---|
| `chave` | sim | identificador (vira `meta_<chave>` no formulário e a chave no JSON) |
| `rotulo` | não | texto mostrado; sem ele, deriva da `chave` |
| `tipo` | não | `texto` (padrão), `numero` ou `escolha` |
| `opcoes` | para `escolha` | lista de valores do `<select>` |
| `obrigatorio` | não | exige preenchimento **quando o campo está visível** |
| `ajuda` | não | texto de apoio abaixo do campo |
| `ordem` | não | posição na tela (menor primeiro) |

Recursos avançados:

- **`visivel_quando`** — o campo só aparece (e só é exigido) quando outro campo
  tem um dos valores: `{"chave": "vinculo", "valores": ["Aluno"]}`.
- **`depende_de` + `opcoes_por`** — as opções do `<select>` mudam conforme o
  valor do campo pai:
  `{"depende_de": "curso", "opcoes_por": {"TPG": ["Primeiro período", …]}}`.

Exemplo em uso (IFMG Campus Ponte Nova):

```python
METADADOS_PARTICIPANTE = [
    {"chave": "vinculo", "rotulo": "Vínculo", "tipo": "escolha", "obrigatorio": True, "ordem": 1,
     "opcoes": ["Aluno", "Servidor", "Colaborador", "Estagiário", "Comunidade externa"]},
    {"chave": "matricula", "rotulo": "Matrícula", "tipo": "texto", "obrigatorio": True, "ordem": 2,
     "visivel_quando": {"chave": "vinculo", "valores": ["Aluno"]}},
    {"chave": "curso", "rotulo": "Curso", "tipo": "escolha", "ordem": 3,
     "opcoes": ["Informática", "Administração", "TPG"],
     "visivel_quando": {"chave": "vinculo", "valores": ["Aluno"]}},
    {"chave": "ano", "rotulo": "Ano/Período", "tipo": "escolha", "ordem": 5,
     "depende_de": "curso",
     "opcoes_por": {"TPG": ["Primeiro período", "Segundo período", "Terceiro período",
                            "Quarto período", "Quinto período"]},
     "visivel_quando": {"chave": "vinculo", "valores": ["Aluno"]}},
    {"chave": "funcao", "rotulo": "Função", "tipo": "escolha", "obrigatorio": True, "ordem": 6,
     "opcoes": ["Professor", "Técnico administrativo"],
     "visivel_quando": {"chave": "vinculo", "valores": ["Servidor"]}},
]
```

Para adaptar a outra escola, basta trocar a lista: quem usa **ano** em vez de
**turma** remove `turma`; outras opções de `curso`/`funcao`; etc. Não há
migração a cada mudança — a configuração é lida a cada requisição.

O comportamento condicional/dependente na tela é do arquivo
`static/js/metadados_dependentes.js`; a validação (obrigatório só quando
visível, dependência válida) é sempre refeita no servidor
(`eventos/metadados.py` + `MetadadosFormMixin`), então continua correta mesmo com
o JavaScript desligado.

## Pré-carga de pessoas (planilha)

Um único arquivo (`.csv`, `.xls` ou `.xlsx`) carrega os dados de **todos os
vínculos** (Aluno, Servidor, Colaborador, Estagiário, Comunidade externa) para a
tabela `PessoaRoster`. No primeiro acesso (Google ou cadastro local), o e-mail é
procurado nessa tabela e os metadados/CPF/nome em falta são preenchidos
automaticamente (ver `eventos/roster.py`).

Colunas: `email`, `nome`, `cpf` + as chaves de `METADADOS_PARTICIPANTE`
(`vinculo`, `matricula`, `curso`, `turma`, `ano`, `funcao`). A
validação é **por vínculo** (Aluno exige matrícula/curso; Servidor exige
função; os demais só o vínculo). Há um arquivo-modelo com dados fictícios em
`exemplo_roster.csv`; para regerá-lo conforme o schema da escola:

```bash
docker compose exec app python manage.py modelo_roster          # exemplo_roster.csv
docker compose exec app python manage.py modelo_roster --xlsx   # .xlsx

# Importar (rode ANTES de as pessoas entrarem — o preenchimento acontece uma vez,
# na criação da conta):
docker compose exec app python manage.py importar_roster /caminho/arquivo.csv
```

O admin (`/admin/eventos/pessoaroster/`) mostra o vínculo, um resumo dos
metadados e a situação da linha (*não usado / usado e confere / usado e
diverge*), e permite ajustes manuais.

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
