# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o
versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

## [Unreleased] — 2.0.0-dev.1

Ciclo **V2.0 — Copiloto do Organizador**: IA/agentes priorizando o workflow do
organizador. Branch de integração `release/v2.0`; a produção (`main`) só recebe
no fim do ciclo, com a tag `v2.0.0`.

### Adicionado

- **Fundação de versão (J0):** fonte única `setup/version.py`, `APP_VERSION`
  sobrescrevível por env, exibida no footer, no dashboard, no admin e no schema
  da API (`/api/v1/`).
- **Configuração central de IA:** `IA_ATIVA` (interruptor geral) e
  `IA_MODELO_TEXTO` / `IA_MODELO_CLASSIFICACAO` (antes espalhados no código).
- **Log de uso de IA:** `eventos.ia` registra operação, modelo e tokens.
- **Pré-triagem de propostas (Onda 1):** sugestão de decisão com score,
  justificativa, tipo do catálogo, conflitos e quase-duplicatas; a IA nunca
  decide — pré-preenche os formulários de aprovar/rejeitar.
- **Importação assistida da programação (Onda 2):** upload de planilha
  (`.csv/.xls/.xlsx`), mapeamento automático das colunas (IA + sinônimos),
  prévia sem gravar e confirmação antes de importar; reaproveita a idempotência
  por título + início de `importacao_programacao`.
- **Copiloto de criação de evento (Onda 2):** a partir de um resumo, propõe
  descrição, tema, blocos de horário e uma programação inicial; as atividades
  são criadas como rascunho com um clique (reusa a importação).
- **Relatórios narrados (Onda 3):** leitura do copiloto no painel de relatórios
  — resumo e ações recomendadas a partir dos indicadores já calculados, com
  fallback determinístico.
- **Briefing operacional (Onda 3):** página de operação do evento (acontecendo
  agora, a seguir e alertas) com leitura do dia gerada por IA.
- **Comunicação assistida (Onda 3):** rascunhos de post/e-mail para divulgação
  a partir dos dados do evento (nada é enviado automaticamente).
- **Concierge do participante (Onda 4):** chat que responde dúvidas sobre a
  programação ancorado nas atividades publicadas (com fallback objetivo e sem
  PII). Porta o padrão de conversa do `mychatbot` para dentro do IFEventos.
- **Assistente — experiência (Onda 4):** indicador de digitação, texto em efeito
  máquina de escrever, autocomplete da programação, links clicáveis (internos na
  mesma aba; externos em nova aba) e layout com campo fixo e rolagem só nas
  respostas.
- **Copilotos ancorados no banco:** dossiê de contexto (`eventos/contexto_ia.py`)
  com catálogo de tipos/espaços, campos do formulário e convenções, usado pela
  importação assistida (normalização de tipo/local, detecção de imagens e
  duplicatas, criação confirmada de itens fora do catálogo), pelo copiloto de
  evento, pela triagem e pelo concierge.
- **Modelos de LLM configuráveis no admin (Onda R0b):** `ContextoIA` permite
  escolher o modelo (e temperatura/max_tokens) de **cada contexto** de IA, sem
  deploy; fallback para os padrões do ambiente (`IA_MODELO_TEXTO` /
  `IA_MODELO_CLASSIFICACAO`). Comando `sincronizar_contextos_ia` mantém os
  contextos em dia.
- **Parâmetros por família de modelo + modelos no admin (Onda R0c):** uso de
  `max_completion_tokens` e omissão de `temperature` em modelos novos
  (`gpt-5*`/o-series), com retry de segurança central (`services.gerar_chat`);
  datalist dos modelos de chat da OpenAI no admin (endpoint cacheado).
- **Relatório por aluno + permissão dos relatórios (Onda R1):** página por
  pessoa (KPIs, tabela, gráficos, filtros e export) com a regra única em
  `relatorios/agregacoes.py`; os relatórios existentes passam a exigir
  `pode_gerenciar_evento` (fecha vazamento de PII); IA de **curadoria** e
  **insights** dos gráficos.
- **Relatório por turma (Onda R2):** agrupamento configurável
  (`?agrupar=`, padrão `curso_turma_ano`), gráficos por grupo, drill-down para o
  relatório por aluno já filtrado e export XLSX com **abas Resumo + Detalhe**
  (extensão `abas=` em `eventos/exportacao.py`).
- **Relatório por tipo de atividade (Onda R3):** grade de atividades com KPIs,
  gráficos e filtro por tipo (`?tipo=`), export CSV/XLSX/PDF; badge
  "outro organizador" no cartão do evento e na tela de atividades quando o
  evento pertence a outro organizador.
- **Minhas palestras (Onda R4):** seção no participante com as atividades em
  que a pessoa é palestrante e o QR de presença para mostrar na sala — sem
  lista de inscritos (PII). Correção pré-existente: o endpoint da API do QR
  usava `IsDonoEvento` e barrava o palestrante, mesmo com a tela liberada.
- **IA nos gráficos nas demais páginas + text-to-chart (Onda R6):** curadoria,
  insights e **gráfico por descrição em linguagem natural** nas páginas por
  participante, por turma e por tipo (`relatorios/_ia_graficos.html`); endpoint
  `grafico_por_descricao` com fallback determinístico por palavra-chave e o
  contexto de IA `graficos_nl`.
- **Refino dos relatórios (dev.17):**
  - **Renome "aluno" → "participante"** em todas as camadas (rotas
    `relatorio_participantes`, views, templates, agregações e ids de gráfico).
  - **"Criar gráfico" agora adiciona um gráfico novo** à página: `graficos.py`
    virou catálogo de specs (`graficos(evento, ids=None)`, `grafico_por_id`) e
    o catálogo do texto é o do evento ∪ o da página; se o gráfico já estiver
    na tela, só destaca.
  - **Feedback visível da IA** (callout com carregando/sucesso/erro), curadoria
    reordena a grade e os endpoints respeitam os filtros da página
    (`?tipo=`, `?agrupar=`, `?grupo=`).
  - **Gutter padronizado** (16px celular / 24px desktop) em todas as telas
    internas (relatórios, dashboard do organizador, importações, operação,
    check-in) e painel de IA responsivo (input + botão sem colar).
  - **Redirecionamento 301** das URLs antigas `relatorio_alunos/...` para
    `relatorio_participantes/...` (com query string preservada), para links e
    bookmarks antigos não caírem em 404 após o rename.

### Alterado

- Formulário de atividade: o campo **Espaço** (antes “Local”) agora é um
  **select do catálogo da escola** (`Espaco`), com a mesma lógica da chamada —
  e botão **“novo”** que cria o espaço no catálogo (sem migration; o nome é
  gravado em `local`).
- Prévia de imagem neutra (1:1 na atividade, 3:1 na capa do evento) no lugar da
  foto do campus.
- Tela de atividades do organizador: removidos os atalhos “Adicionar novo
  palestrante” e “Adicionar novo tipo de atividade” (seguem disponíveis ao
  criar/editar a atividade).
- `eventos/services.py` passa a ler os modelos de `settings` e a respeitar
  `IA_ATIVA`; sem chave de API ou com a IA desligada, cai no fallback
  determinístico.

## [1.0.0] — anterior ao ciclo V2.0

- Portal de eventos do IFMG Campus Ponte Nova: programação, inscrições, check-in
  por QR code, crachás, certificados, relatórios, chamada de proposições e API
  REST (com servidor MCP).
