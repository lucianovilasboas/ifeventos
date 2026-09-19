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
