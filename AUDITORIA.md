# Auditoria (rastreabilidade)

Trilha **append-only** de ações do sistema, para acompanhar o que acontece em
produção e achar problemas. A aplicação nunca edita nem apaga estas linhas; o
admin é **somente leitura**.

## Modelo `RegistroAuditoria`

`eventos/models.py`. Campos principais:

| Campo | Para quê |
|---|---|
| `criado_em` | quando (indexado) |
| `request_id` | correlaciona as linhas de uma mesma requisição |
| `usuario` + `usuario_nome`/`usuario_email` | quem (snapshot sobrevive à exclusão) |
| `origem` | `web` / `api` / `admin` / `cli` / `sistema` |
| `acao` | criar, editar, excluir, login, logout, emitir_certificado, aprovar_proposta, rejeitar_proposta, cancelar_proposta, importar, configurar_certificado, checkin, cancelar_presenca, erro |
| `entidade` + `objeto_id` + `objeto_repr` | o que (rótulo em texto sobrevive à exclusão) |
| `evento` | evento relacionado (escopo por evento) |
| `resumo` | frase curta legível |
| `detalhes` (JSON) | antes/depois no editar; dados extra |
| `ip`, `path`, `metodo`, `status` | onde/como |

## O que é registrado

**Automático (signals — `eventos/signals.py`)**
- **criar/editar/excluir**: `Evento`, `Atividade`, `Espaco`, `Vaga`, `ChamadaProposicoes`.
  No editar, só grava se um campo relevante mudou (guarda `antes`/`depois`).
- **criar**: `Inscricao`, `Presenca`.
- **login/logout**: sinais do próprio Django (`user_logged_in`/`user_logged_out`),
  que cobrem o login do site (allauth), o admin e os testes.

**Explícito (ações de negócio — nas views)**
- **`emitir_certificado`**: por inscrição, por atividade, do evento e de todas as
  atividades.
- **`configurar_certificado`**: salvar a config do evento/padrão e da atividade.
- **`aprovar_proposta`** / **`rejeitar_proposta`**.
- **`cancelar_presenca`**: em `Presenca.cancelar` (além do `PresencaCancelada`).

## Como consultar

- **Admin do Django** → *Registros de auditoria*: filtros por data/ação/entidade/
  origem, busca por usuário/resumo/objeto, `date_hierarchy`. Sem adicionar/editar/
  apagar.

## Privacidade

- **CPF** e **e-mail** são **mascarados** dentro de `detalhes`
  (`eventos.auditoria._sanitizar`). Senhas/tokens nunca são gravados.
- A exposição por API/agente (fase futura) reaproveita `mascarar_cpf`/`mascarar_email`.

## Roadmap

- **Fase 2** — API read-only (`/api/v1/auditoria/`) + agregações, para um agente
  externo/MCP consultar via token.
- **Fase 3** — agente interno "AuditorIA" (pergunta em linguagem natural → consulta
  estruturada no ORM → resumo).
- **Fase 4** — captura de erros (self-contained e/ou Sentry).
- **Fase 5** — retenção (`limpar_auditoria --dias 90`).

## Operação

O contexto da requisição (usuário/IP/path) é guardado num thread-local pelo
`eventos.middleware.AuditoriaContextoMiddleware`, para signals e para o helper
`eventos.auditoria.registrar(...)`.
