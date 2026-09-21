# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o
versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

## [2.2.10] — 2026-09-21

### Alterado

- **"Equipe de apoio" mudou de lugar**: o botão saiu da tela de atividades do
  evento (`/organizador/atividades_evento/<id>/`) e foi para o **painel do
  organizador** (`/organizador/dashboard/`), como um **ícone por evento** na
  fileira de ações de cada card (logo antes do "Excluir"). Abre um modal único
  com a gestão da equipe daquele evento (adicionar por e-mail, ver membros,
  remover e senha temporária quando cria conta mínima), com os dados embutidos
  no dashboard.

## [2.2.9] — 2026-09-21

### Alterado

- **Programação sem o banner da home**: a página `/eventos/programacao/<id>`
  deixou de mostrar o hero "Eventos do IFMG / Fique por dentro dos eventos e
  programações do campus." (o bloco `hero` do `base.html` virou sobrescrevível
  e a programação o esvazia). As telas de conta (login, cadastro, senha) e a
  redefinição de senha continuam com o banner.

## [2.2.8] — 2026-09-21

### Alterado

- **Palestrante agora é opcional na atividade**: o formulário de criar/editar
  atividade do organizador aceita atividade **sem palestrante** (o campo
  deixou de ser obrigatório; o `*` saiu do rótulo). Exposições, feiras e
  atividades sem ministrante formal podem ser cadastradas. O restante do
  sistema já suportava (API, proposta, copiloto, importação, crachás,
  relatórios, certificado) — inclusive já havia atividades sem palestrante em
  produção. A exibição continua deixando a linha em branco quando não há
  palestrante.

## [2.2.7] — 2026-09-21

### Adicionado

- **Identificação de superusuário no avatar**: quando conectado com uma conta de
  superusuário, o avatar do topo ganha um **anel amarelo** no contorno (com um
  leve brilho) e um **badge pequeno "S"** no canto — para o administrador saber
  na hora que está logado com a conta de superusuário. Vale em todas as telas
  do app e na página inicial (landing).

## [2.2.6] — 2026-09-21

### Corrigido

- **"Definir senha" com o layout do app**: a página de definição de senha
  (allauth, para contas sem senha — ex.: login social) usava o template padrão
  do allauth: ficava sem estilo e mostrava o menu antigo ("Menu: Alterar
  e-mail / Alterar senha / Conexões de conta / Sair"). Agora tem template
  próprio (`account/password_set.html`) no mesmo padrão das outras telas de
  conta ("Alterar senha", "Redefinir senha"): container estilizado, campos com
  rótulo e ícone de cadeado, erros por campo, as regras da senha exibidas e o
  botão **"Definir senha"**. O menu do allauth desapareceu.

## [2.2.5] — 2026-09-21

### Corrigido

- **Perfil — erros de validação agora aparecem**: quando o formulário de perfil
  falha ao salvar (ex.: campos obrigatórios vazios como **Vínculo** ou **CPF**),
  o modal **reabre automaticamente mostrando os erros por campo** e o usuário
  vê por que nada foi gravado (antes o modal reabria "zerado", sem nenhum
  aviso, parecendo que o sistema não salvava). O POST inválido já retornava o
  dashboard com o formulário ligado — agora esse formulário (com os erros) é
  repassado ao modal e o modal é aberto.
- **Erro duplicado removido**: "Este campo é obrigatório." aparecia duas vezes
  para os campos de metadados obrigatórios (a obrigatoriedade era cobrada no
  campo **e** na validação). A validação agora é a fonte única — uma mensagem só.
- **Detalhe**: o formulário de perfil exige **Vínculo** (e **CPF**) — são campos
  obrigatórios. Contas criadas sem esses dados (ex.: organizadores vindos do
  Google/admin) só salvam o perfil depois de preenchê-los no modal, e agora a
  tela avisa qual campo está faltando.

## [2.2.4] — 2026-09-20

### Corrigido

- **Grade de programação — coluna de horários recortando o primeiro dia ao
  rolar**: o gutter da grade ficava no `padding` do contêiner de rolagem
  (`.agenda-scroll`). Como a coluna de horários é `position: sticky`, o
  conteúdo rolado aparecia **na faixa de padding à esquerda dela** (por baixo
  da coluna), recortando o cabeçalho do dia e os eventos e abrindo um vão —
  a primeira coluna do calendário ficava com deslocamento horizontal indevido,
  com elementos passando do limite esquerdo da área de visualização. O gutter
  agora vai para a `margin` do contêiner (fora da área de rolagem): o conteúdo
  é recortado corretamente na borda da coluna sticky, sem vazar. Válido para
  as 5 telas que usam a grade (programação pública, grade do organizador,
  "Minha agenda" do participante, ocupação de salas e mapa de calor).

## [2.2.3] — 2026-09-20

### Corrigido

- **Grade de programação — coluna de horários recortando a programação**: a
  primeira coluna do calendário (horários) apresentava um deslocamento
  horizontal indevido, ocasionando o recorte parcial dos eventos e do cabeçalho
  do dia (os elementos passavam do limite esquerdo da área de visualização ao
  rolar a grade na horizontal). Causa: a coluna não tinha largura fixa e, com a
  tabela `width:100%` + `min-width:640px`, ela absorvia o espaço livre e esticava
  (até ~144px em grids com poucos dias). Agora a coluna tem **largura fixa de
  48px** em todas as telas, com borda de separação — os horários voltam para a
  esquerda, o grid fica alinhado e o recorte ao rolar é mínimo.
  - Vale para todas as telas que usam a tabela `.agenda`: programação pública,
    grade do organizador, "Minha agenda" do participante, ocupação de salas e
    mapa de calor.

## [2.2.2] — 2026-09-20

### Corrigido

- **Autorização das rotas do organizador**: várias rotas de escrita estavam
  abertas a qualquer usuário logado (até um participante comum). Agora seguem
  a regra do sistema (`pode_gerenciar_evento` — organizador opera o evento):
  - Publicar/excluir atividade, criar/editar atividade (formulário e modal),
    página de gestão das atividades → participante/equipe levam **403**.
  - Ações globais passam a exigir a flag de organizador (403 para quem não
    tem): criar evento, cadastrar palestrante, tipo de atividade, espaço e o
    download do modelo CSV de metadados.
  - Emissão de certificados (por inscrição, por atividade e por evento) agora
    exige login + organizador — antes nem exigia login.
  - Endpoints de IA (descrição, sugerir categoria e mensagem do dia) agora são
    **somente organizadores** (evita uso indevido dos créditos da API).
- A equipe de apoio (`/apoio/`) não é afetada: continua fazendo o check-in das
  atividades dos eventos vinculados, mas não abre a gestão do organizador.

## [2.2.1] — 2026-09-20

### Alterado

- **Início/Agenda sempre perto do avatar**: no desktop, a navegação da topbar
  deixou de ficar centralizada e agora fica **colada à direita, junto ao
  avatar**, em todas as telas do app (mesmo comportamento da Home).
- **Header e footer full-width**: a barra do topo e o rodapé agora ocupam a
  **largura toda da página** (desktop e mobile), como na Home — o conteúdo
  deles continua centrado a 1080px. Antes a topbar ficava limitada a 1080px
  centrada no desktop. O rodapé do app virou uma barra com borda superior
  (espelhando a Home), em vez de uma linha de versão solta.

## [2.2.0] — 2026-09-20

### Adicionado

- **Equipe de apoio** (`is_equipe` + `Evento.equipe`): perfil de usuário para
  quem ajuda durante o evento com o check-in, **sem poderes de organização**.
  - O **organizador** gerencia a equipe na tela de atividades do evento (botão
    "Equipe de apoio"): adiciona por e-mail, lista e remove. E-mail já
    cadastrado **reaproveita a conta** (participante/palestrante só ganha o
    papel e o vínculo); e-mail novo cria **conta mínima** (senha temporária
    mostrada uma única vez, e-mail já marcado como verificado — sem pedir CPF).
  - A pessoa da equipe vê a visão **"Apoio"** (novo painel `/apoio/`): eventos
    em que foi adicionada, a programação (atividades publicadas com horário,
    sala, tipo e inscritos) e, em cada atividade, **check-in pela câmera**
    (QR do crachá), **código manual** e **desfazer presença** — reutilizando o
    fluxo de check-in existente. Também pode **exibir o QR de presença** da
    atividade (projetar na sala).
  - Permissões: `pode_checkin_apoio` libera o check-in/QR/desfazer só nos
    eventos vinculados àquela pessoa; quem é equipe de outro evento recebe 403.
    Presenças registradas guardam `registrada_por` (auditoria). Nada de
    criar/editar/excluir eventos ou atividades, relatórios, certificados,
    propostas, comunicação ou crachás.
  - Menu: toggle **"Trocar para Apoio"** quando a pessoa tem o papel; quem tem
    várias visões (participante/palestrante/equipe) alterna entre elas.

## [2.1.6] — 2026-09-20

### Alterado

- **Conflitos na grade compactos**: o aviso "Possíveis conflitos na grade" deixou
  de ser um alerta grande com a lista inteira. Agora é uma **barra pequena**
  ("N conflito(s) na grade" + botão **"Ver detalhes"**) que abre um **modal**
  com todos os conflitos, cada um mostrando o tipo (mesma sala / mesmo
  palestrante), o local/pessoa, o horário e **links para editar** as duas
  atividades envolvidas.
- **Modelo de crachá ativo destacado**: no menu "Imprimir crachás", o modelo
  atualmente ativo do evento aparece **em verde** (fundo verde-claro, texto
  verde e check), para o organizador saber qual está valendo sem precisar abrir.

## [2.1.5] — 2026-09-20

### Alterado

- **Botões de IA destacados**: nova classe `.btn-ia` (violeta `#7c3aed`) aplicada a
  todos os botões de geração por IA do app — gerar descrição (evento/atividade),
  sugerir categoria, copiloto (gerar plano / criar atividades), divulgação,
  sugerir tipo (proposta), analisar com IA (propostas) e sugestão/insights/
  criar gráfico (relatórios). Botões ao lado de campos ganharam `.btn-campo`
  para ficarem na mesma altura (ex.: "Gerar" da divulgação).
- **Emojis nos textos gerados por IA**: divulgação (post e e-mail), descrição do
  evento e descrição do copiloto agora usam **1 a 2 emojis por parágrafo**,
  coerentes com o conteúdo (sem poluir).
- **Copiloto — remover rascunho**: após "Criar atividades (rascunho)", aparece o
  botão **"Remover rascunho"** que apaga só as atividades **não publicadas**
  criadas pelo plano (endpoint novo `remover_plano_evento`, com guarda para não
  apagar publicada/de outro evento). `importar_linhas` passa a registrar o `id`
  das atividades criadas no relatório.

## [2.1.4] — 2026-09-20

### Alterado

- **Cartões de evento (dashboard)**: "Editar" subiu para o topo do cartão e
  "Excluir" foi para a ponta direita da barra de ações — longe um do outro,
  para evitar clique acidental em excluir.
- **Criação de evento (modal)**: após criar, o usuário vai direto para a
  **edição do evento** (onde ficam o copiloto, a divulgação e as demais
  ferramentas de IA); dica adicionada na modal.
- **Página de atividades**: botões reorganizados — destaque para "Criar
  atividade" e "Imprimir crachás" (dropdown único com "Imprimir (PDF)" +
  seleção do modelo do crachá, sem `<form>` aninhado); "Operação" e os
  relatórios (participante, turma, tipo) agora ficam num dropdown
  "Relatórios e operação".
- **Descrição de evento com IA**: prompt reformulado para gerar 2–3 parágrafos
  profissionais, com foco no público-alvo, mencionando a programação quando
  disponível (títulos das atividades publicadas) e tom institucional/neutro,
  porém chamativo.

## [2.1.3] — 2026-09-20

### Corrigido

- **Botão "Aprovar" da tela de propostas pendentes**: o botão "Cadastrar tipo"
  (adicionado no 2.1.2) era um `<form>` **aninhado** dentro do form de
  aprovação — o `</form>` interno fechava o form externo e o botão "Aprovar"
  ficava órfão (não enviava). Agora o "Cadastrar tipo" é um botão com
  `formaction`, sem aninhar, e o form de aprovação volta a funcionar.
  Teste de regressão (detecção de `<form>` aninhado na tela).

## [2.1.2] — 2026-09-20

### Corrigido / Adicionado (formulário de proposta e aprovação)

- **Preview e recorte da imagem preservados** quando a validação falha: o
  `cropped_image` (data URL) volta para a prévia e é reenviado — o usuário não
  precisa recortar de novo.
- **Tela de aprovação do organizador**:
  - mostra a **imagem** enviada pelo proponente;
  - botão **"Cadastrar tipo"** quando o proponente sugeriu um tipo fora do
    catálogo (cria o `TipoAtividade` e já o seleciona; a aprovação continua
    explícita no botão Aprovar).
- **Checagem "já cadastrado" na proposição**: ao sugerir um palestrante por
  e-mail, se a pessoa já existe no sistema ela é **marcada como palestrante**
  (com aviso) em vez de virar sugestão — só chegam ao organizador sugestões de
  quem realmente não está cadastrado. Guarda também no servidor (`propor`/
  `atualizar`).

## [2.1.1] — 2026-09-20

### Corrigido (formulário de proposta)

- **Não apaga o que o usuário preencheu**: quando a validação falha, os chips
  de palestrante escolhido e de palestrante sugerido são preservados (antes
  sumiam ao recarregar a página).
- **"Eu vou ministrar esta atividade"**: agora vem **marcado por padrão** e
  aparece logo no topo da seção "Quem apresenta" (na edição, reflete se o
  proponente já é palestrante da proposta).
- **Select múltiplo de palestrantes removido** (expunha a lista de nomes): a
  escolha passa a ser só pela **busca** (nome/e-mail → chips) e pela sugestão
  de palestrante novo.
- **Imagem com recorte (Cropper)**: o campo de imagem da proposta agora usa o
  mesmo recorte/preview do formulário de atividade do organizador.

## [2.1.0] — 2026-09-20

### Adicionado (formulário de proposta)

- **Consentimento de participação voluntária**: switch obrigatório com o texto
  *"Estou ciente de que a participação é voluntária e não remunerada."* — sem
  marcar, a proposta não é enviada. Guardado em
  `Atividade.consentimento_voluntario`.
- **Recursos e itens necessários**: campo de texto livre
  (`Atividade.recursos_necessarios`) para o palestrante descrever o que precisa.
  Não é público — fica na área do organizador (revisão da proposta e edição da
  atividade, quando é proposta).
- **Palestrante sugerido** (novo model `PalestranteSugerido`): o proponente pode
  sugerir coautores que ainda não estão cadastrados (nome + e-mail + telefone
  opcional). O organizador converte com "Cadastrar palestrante": se o e-mail já
  existir, vincula ao cadastro existente (sem duplicar); senão cria um
  Participante palestrante e o adiciona à atividade.
- Migration `0036_atividade_consentimento_voluntario_and_more` (novos campos +
  model `PalestranteSugerido`, registrado no admin).

## [2.0.1] — 2026-09-20

### Corrigido

- **Concierge — "qual é o evento de hoje"**: o chat respondia com o primeiro
  item da programação em vez do dia atual, porque o prompt não tinha a data de
  hoje nem as datas do evento. Agora o contexto leva a **data/hora atuais**
  (AGORA), o **período dos eventos** e cada atividade com **data absoluta +
  etiqueta relativa** (`hoje`, `amanhã`, `em N dias`, `acontecendo agora`).

### Adicionado

- **Contexto rico do concierge**: o chat passa a ter acesso à **programação
  completa** dos eventos em andamento/futuros (título, tipo, descrição,
  palestrantes por nome, local, horários, vagas, emissão de certificado e
  período do evento), permitindo responder perguntas com raciocínio de datas
  ("quantos dias faltam?", "o evento acontece quando?"). Sem PII (nada de
  e-mail/CPF/telefone). Limites: 300 atividades e descrição em 240 caracteres.

## [2.0.0] — 2026-09-19

Ciclo **V2.0 — Copiloto do Organizador**: IA/agentes priorizando o workflow do
organizador. Entrega consolidada após as ondas R0b–R6 e os refinamentos de UI.

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
- **Gutter padronizado nas telas antigas (dev.19):** todos os painéis das telas
  internas passam a guardar o mesmo respiro lateral (16px celular / 24px
  desktop). Aplicado em: painel da chamada, chamada de propostas, propostas
  pendentes, minhas propostas, propor atividade, minhas palestras, assistente,
  crachás (só o topo), programação pública e formulários de evento/atividade/
  perfil. O `.app-page` agora neutraliza o gutter de `.app-list/.app-stats/
  .cards-h` aninhados, evitando padding duplicado.
- **Gutter nas telas de conta/senha (dev.20):** os painéis de autenticação
  (login, cadastro, sair, redefinir senha, alterar senha, confirmação de
  e-mail e telas sociais) passam a guardar o mesmo respiro lateral padrão —
  antes colados nas bordas (0px) ou com 12px do Bootstrap. A confirmação de
  "senha alterada" (`password_reset_from_key_done`) ganhou painel próprio.

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
