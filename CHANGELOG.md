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

### Alterado

- `eventos/services.py` passa a ler os modelos de `settings` e a respeitar
  `IA_ATIVA`; sem chave de API ou com a IA desligada, cai no fallback
  determinístico.

## [1.0.0] — anterior ao ciclo V2.0

- Portal de eventos do IFMG Campus Ponte Nova: programação, inscrições, check-in
  por QR code, crachás, certificados, relatórios, chamada de proposições e API
  REST (com servidor MCP).
