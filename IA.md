# IA — Contextos de IA (ponto único de configuração)

Todo o uso de modelos de IA do sistema é centralizado aqui. Cada recurso de IA
tem uma **chave de contexto** e chama `eventos.services.gerar_chat(chave, …)`;
ninguém usa o cliente da OpenAI direto. Isso permite **configurar, habilitar e
desabilitar** cada recurso **sem deploy**.

## Onde configurar

**Admin → Contextos de IA** (`/admin/eventos/contextoia/`). Por contexto:

| Campo | O que faz |
|---|---|
| **Modelo de LLM** | qual modelo usar (ex.: `gpt-4o`, `gpt-4o-mini`). Vazio = padrão do ambiente. |
| **Temperatura** / **Máx. tokens** | ajustes finos (vazio = default do código). |
| **Ativo** | liga/desliga **aquele** recurso. Desligado → o recurso cai no fallback determinístico (sem IA), sem erro. |

Salvar já invalida o cache — passa a valer na hora. A coluna **Modelo efetivo**
mostra o que está sendo realmente usado (o do admin ou o padrão).

## Chaves de contexto

| Chave | Recurso |
|---|---|
| `mensagem_usuario` | Mensagem do dia |
| `descricao_evento` | Descrição de evento/atividade |
| `sugerir_categoria` | Sugerir tema do evento |
| `sugerir_tipo` | Sugerir tipo de atividade (proposta) |
| `concierge` | Assistente da programação (participante) |
| `triagem_propostas` | Pré-triagem de propostas |
| `importacao_mapeamento` | Importação assistida da programação |
| `copiloto_evento` | Copiloto de criação de evento |
| `briefing_operacional` | Briefing operacional |
| `auditoria` | Auditoria (perguntas sobre ações) — **superusuário** |
| `comunicacao` | Comunicação (divulgação) |
| `relatorio_narrado` | Relatórios narrados |
| `graficos_curadoria` | Curadoria de gráficos |
| `graficos_nl` | Gráfico por descrição (NL) |
| `graficos_insights` | Insights dos gráficos |

## Liga/desliga global

- `IA_ATIVA=False` no `.env` desliga **toda** a IA (os recursos caem nos
  fallbacks). `IA_MODELO_TEXTO`/`IA_MODELO_CLASSIFICACAO` definem os **modelos
  padrão** quando o contexto não tem um modelo escolhido no admin.

## Como os contextos são criados/manidos

O registro canônico é `eventos/ia_config.py::CONTEXTOS` (código). A tabela
`ContextoIA` (banco) guarda só o que o admin escolhe.

- No **deploy**, o `entrypoint.sh` roda `python manage.py sincronizar_contextos_ia`
  a cada start: cria contextos novos e atualiza rótulo/grupo/padrão/ordem,
  **sem tocar** no modelo/temperatura/max_tokens/ativo escolhidos no admin.
- Manualmente: `python manage.py sincronizar_contextos_ia` (idempotente).

> Contextos novos entram pelo comando (o deploy roda as migrations, não o
> comando) — por isso o sync automático no entrypoint garante que nada fique
> faltando no admin.
