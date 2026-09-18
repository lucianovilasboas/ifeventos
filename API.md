# API do IF Eventos

API REST (Django REST Framework) que expõe o mesmo domínio do site: eventos,
atividades, inscrições, presenças, crachás, certificados e a chamada de
proposições. Foi feita para **app externo e LLM (MCP)** — a regra de negócio é a
mesma do site, não uma reimplementação: os endpoints chamam os serviços de
`eventos/` (`propostas`, `inscricoes`, `crachas`, ...), então tela e API contam a
mesma história.

- **Base:** `/api/v1/`
- **Swagger:** `/api/v1/docs/` · **Redoc:** `/api/v1/redoc/` · **schema:** `/api/v1/schema/`
- Dev: `http://127.0.0.1:8501/api/v1/` — Prod: `https://ifeventos.lucianovilasboas.com.br/api/v1/`

## Autenticação

Dois modos, ambos ativos:

| Modo | Como | Onde usar |
| --- | --- | --- |
| Token | `Authorization: Token <chave>` | app externo, script, MCP/LLM |
| Sessão | cookie da sessão do site | navegador já logado |

O login é por **e-mail** (não username).

```bash
# 1) trocar email+senha por um token
curl -s -X POST https://.../api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"email":"alguem@exemplo.com","password":"..."}'
# -> {"token":"...","user_id":123,"email":"alguem@exemplo.com"}

# 2) usar o token
curl -s https://.../api/v1/eventos/ -H "Authorization: Token <chave>"
```

Cadastro de participante pela API: `POST /api/v1/auth/registro/` com
`{email, password (>=6), cpf, first_name?, last_name?, telefone?}` — cria conta
`is_participante=True` e já devolve o token.

**Usuário de serviço** (para automação/MCP), no servidor:

```bash
docker exec app_django bash -lc 'cd /ifeventos && python manage.py drf_create_token api-servico@local.dev'
```

O comando **não rotaciona** um token existente: se precisar trocar, apague o
token antes (`Token.objects.filter(user__email="...").delete()`).

Sem token válido, endpoints autenticados respondem **403** (não 401): a
autenticação por sessão do DRF não manda o cabeçalho `WWW-Authenticate`.

## Convenções

- **Paginação** (lista): `?page=N`, 50 por página; a resposta é
  `{"count", "next", "previous", "results"}`.
- **Busca** `?search=`: eventos (`title`, `description`, `local`), atividades
  (`titulo`, `descricao`), palestrantes (`first_name`, `last_name`, `email`),
  espaços (`nome`).
- **Filtros por query** onde fizer sentido: `?evento=`, `?situacao=`, `?minhas=1`,
  `?atividade=`, `?participante=`, `?espaco=`.
- Datas em ISO 8601. `date` é `YYYY-MM-DD`; `datetime` é
  `YYYY-MM-DDTHH:MM:SS-03:00` (o fuso do sistema).
- Erros de validação vêm por campo: `{"campo": ["mensagem"]}`; bloqueios de
  regra vêm como `{"detail": "mensagem"}` (a mesma mensagem que a tela mostra).

## Permissões (a regra real do sistema)

- **Catálogo público** (leitura sem login): eventos, atividades publicadas,
  tipos de atividade, espaços.
- **`is_organizador`** é uma flag **global**: quem tem a flag **opera qualquer
  evento** (check-in, presenças, chamada, decidir proposta). É a mesma regra do
  site (`eventos.crachas.pode_gerenciar_evento`).
- **Editar conteúdo** (criar/editar/excluir evento, atividade, vaga) é do
  **dono do evento** (`Evento.organizador`) ou superuser — `IsDonoEvento`.
- **Dados pessoais** (palestrantes, metadados): exigem a flag em **qualquer**
  método, inclusive leitura (`IsOrganizadorEstrito`), porque trazem CPF,
  telefone e endereço.
- **Rascunho e proposta pendente não são catálogo público**: a leitura anônima
  de atividades filtra `publicada=True`.

## Endpoints

### Autenticação e perfil

| Método | Rota | Quem |
| --- | --- | --- |
| POST | `auth/token/` | público |
| POST | `auth/registro/` | público |
| GET/PATCH | `meu-perfil/` | autenticado (o próprio) |
| GET | `metadados/` | organizador (schema dos campos por escola) |
| POST | `participantes/importar-metadados/` | organizador (upsert por e-mail) |

### Eventos

| Método | Rota | Quem |
| --- | --- | --- |
| GET | `eventos/` · `eventos/{id}/` | público |
| POST | `eventos/` | organizador (`organizador` no corpo) |
| PUT/PATCH/DELETE | `eventos/{id}/` | dono/superuser |
| GET/PUT | `eventos/{id}/chamada/` | GET: autenticado · PUT: organizador dono |
| GET | `eventos/{id}/painel-chamada/` | organizador |
| POST | `eventos/{id}/vagas/gerar/` | organizador dono |
| GET | `eventos/{id}/crachas.pdf` | organizador (`pode_gerenciar_evento`) |

### Tipos de atividade e palestrantes

| Método | Rota | Quem |
| --- | --- | --- |
| GET | `tipos-atividade/` · `tipos-atividade/{id}/` | público |
| POST/PUT/PATCH | `tipos-atividade/` · `/{id}/` | organizador |
| GET/POST/PUT/PATCH | `palestrantes/` · `/{id}/` | organizador (leitura também; sem DELETE) |

`palestrantes/` busca por `first_name`, `last_name`, `email`. O POST é
idempotente por e-mail: se a conta existe, atualiza e garante o papel do
palestrante (200); conta nova devolve 201. Não há DELETE — apagar a conta
quebraria atividades e inscrições; o papel se remove mexendo na pessoa.

### Atividades

| Método | Rota | Quem |
| --- | --- | --- |
| GET | `atividades/` · `atividades/{id}/` | público (só `publicada=True`) |
| POST | `atividades/` | organizador |
| PUT/PATCH/DELETE | `atividades/{id}/` | dono/superuser |
| GET | `atividades/{id}/qrcode/` | organizador do evento ou palestrante da atividade |
| GET | `atividades/{id}/qrcode.png` | idem (imagem crua) |

`POST /atividades/` aceita `vaga` (opcional): quando vem, **o local e a janela
saem da vaga** (não se digita horário divergente) e a vaga precisa estar livre.
Sem `vaga`, `local`, `data_hora_inicio` e `data_hora_fim` continuam obrigatórios.

### Inscrições, presenças, crachás e certificados

| Método | Rota | Quem |
| --- | --- | --- |
| GET | `minhas-inscricoes/` | autenticado (as próprias; organizador vê as que gerencia) |
| POST | `minhas-inscricoes/` | autenticado (self-inscrição em `{atividade}`) |
| DELETE | `minhas-inscricoes/{id}/` | dono da inscrição ou organizador |
| GET | `meus-certificados/` · `meus-certificados/{id}/` | autenticado (os próprios) |
| GET | `meus-crachas/` | autenticado (um por evento com papel) |
| GET | `meus-crachas/{evento_id}/qr.png` | autenticado |
| GET/POST/DELETE | `presencas/` | organizador do evento |
| GET | `verificar/{token}/` | **público** (crachá ou certificado; sem dados pessoais) |

O check-in (`POST /presencas/`) aceita três formas, como na portaria:
`{atividade, participante}` (marcação manual), `{atividade, codigo}` (código
ditado) ou `{token_atividade}` (a própria pessoa confirma pelo QR da atividade).

### Catálogo de espaços (chamada)

| Método | Rota | Quem |
| --- | --- | --- |
| GET | `espacos/` · `espacos/{id}/` | público |
| POST | `espacos/` | organizador |
| PUT/PATCH/DELETE | `espacos/{id}/` | organizador |

O espaço é da **escola** (catálogo reaproveitado entre eventos), com `nome`
único e `capacidade` sugerida.

### Grade de vagas

| Método | Rota | Quem |
| --- | --- | --- |
| GET | `vagas/` (`?evento=`, `?espaco=`) | autenticado |
| POST | `vagas/` | organizador |
| PUT/PATCH/DELETE | `vagas/{id}/` | organizador dono do evento |

`POST /vagas/` usa as **mesmas regras da tela** (`propostas.validar_vaga`):
janela dentro do período do evento, sem duplicar espaço+janela e — se a vaga já
tem proposta ativa — espaço e horário ficam travados (a capacidade ainda muda).

### Propostas (chamada de proposições)

| Método | Rota | Quem |
| --- | --- | --- |
| GET | `propostas/` | autenticado (participante vê só as próprias; organizador vê todas) |
| POST | `propostas/` | autenticado (propõe) |
| PATCH | `propostas/{id}/` | autor (enquanto pendente e com a chamada aberta) |
| DELETE | `propostas/{id}/` | autor cancela (pendente) **ou** organizador remove (sempre) |
| POST | `propostas/{id}/aprovar/` | organizador |
| POST | `propostas/{id}/rejeitar/` | organizador (motivo obrigatório) |

Filtros: `?evento=`, `?situacao=pendente|aprovada|rejeitada`, `?minhas=1`.

Corpo da proposta (o espaço/horário **não** vêm soltos — vêm da vaga):

```json
{
  "vaga": 12,
  "titulo": "Oficina de robótica",
  "descricao": "Descrição da proposta",
  "tipo": 3,
  "tipo_sugerido": "Robótica",
  "palestrantes": [45, 46],
  "n_vagas": 30,
  "emite_certificado": true
}
```

`tipo` é obrigatório (na criação); `tipo_sugerido` é texto livre (a sugestão por
IA do site). Aprovar aceita `{"publicar": true, "tipo": 3}` — por padrão já
publica na programação. Rejeitar exige `{"motivo": "..."}`.

## Fluxo completo da chamada (exemplo)

```bash
T="Authorization: Token <chave>"
H="Content-Type: application/json"
B="https://.../api/v1"

# 1) organizador abre a janela
curl -s -X PUT "$B/eventos/107/chamada/" -H "$T" -H "$H" \
  -d '{"inicio":"2026-10-01T00:00:00-03:00","fim":"2026-10-05T23:59:00-03:00","aberta":true}'

# 2) monta a grade em lote (dias x blocos x espaços; idempotente)
curl -s -X POST "$B/eventos/107/vagas/gerar/" -H "$T" -H "$H" \
  -d '{"dias":["2026-10-05","2026-10-06"],"blocos":["08:00-10:00","10:00-12:00"],"espacos":[1,2],"capacidade":1}'
# -> {"criadas": 8, "existentes": 0}   (rodar de novo: {"criadas": 0, ...})

# 3) quem propõe lê a janela e o que está livre
curl -s "$B/eventos/107/chamada/" -H "$T"
# -> {..., "aberta_agora": true, "vagas_livres": [{"id":12,"espaco":"Auditório",...}]}

# 4) propõe escolhendo uma vaga
curl -s -X POST "$B/propostas/" -H "$T" -H "$H" \
  -d '{"vaga":12,"titulo":"Oficina","descricao":"...","tipo":3,"n_vagas":30}'

# 5) o organizador vê os números e decide
curl -s "$B/eventos/107/painel-chamada/" -H "$T"      # KPIs, ocupação, livres
curl -s -X POST "$B/propostas/227/aprovar/" -H "$T" -H "$H" -d '{"publicar":true}'
# ou: .../rejeitar/ -d '{"motivo":"Fora do tema"}'
```

Observações de comportamento:

- Propor exige janela **aberta** (a checagem é sempre refeita no servidor),
  vaga **livre**, sem conflito de horário/local e respeitando
  `MAX_PROPOSTAS_POR_PROPONENTE` (0 = sem limite).
- A vaga é travada com `select_for_update`: "quem propõe primeiro leva" vale
  mesmo com dois envios simultâneos.
- Rejeitar libera a vaga sozinho — `Vaga.ocupadas` conta proposta pendente,
  aprovada e atividade criada pelo organizador; não conta a rejeitada.
- `POST /atividades/` com `vaga` também reserva a vaga (mesma regra).
