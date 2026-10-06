# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o
versionamento segue [SemVer](https://semver.org/lang/pt-BR/).

## [2.18.6] — 2026-10-06

### Alterado

- **Painel do participante**: removidos os avisos textuais sobre limiar e inelegibilidade do certificado; o marcador positivo continua sendo exibido apenas quando aplicável.

## [2.18.5] — 2026-10-05

### Adicionado

- **Tela de preparação de listas**: botão para limpar todos os filtros e retornar à configuração padrão.

## [2.18.4] — 2026-10-05

### Alterado

- **Painel do participante**: texto do requisito de participação do certificado simplificado para `Certificado do evento: mínimo de X% de participação`, mantendo o percentual dinâmico configurado no evento.

## [2.18.3] — 2026-10-05

### Corrigido

- **PDF das listas de presença**: cada folha repete o cabeçalho geral do evento, o nome da atividade e o grupo curso/turma/ano antes da tabela.

## [2.18.2] — 2026-10-05

### Corrigido

- **PDF das listas de presença**: cada grupo inicia em uma nova página e as tabelas ocupam toda a largura útil da folha, respeitando as margens laterais.

## [2.18.1] — 2026-10-05

### Corrigido

- **Lista de confirmação de presença**: o nome da atividade passou para o cabeçalho de cada bloco, a coluna foi removida e ausências passaram a aparecer como `x Ausente` em vermelho.

## [2.18.0] — 2026-10-05

### Adicionado

- **Tela organizada de preparação de listas de presença** no dashboard do organizador, com filtro por atividade, dia e situação, agrupamento por vínculo/curso/turma/ano, folha de assinatura, lista administrativa de confirmação e geração de PDF.
- Novo atalho **Preparar listas de presença** em cada cartão de evento do dashboard.
- A nova funcionalidade é somente de consulta e não altera modelos, check-in, certificados ou as rotas antigas.

## [2.17.0] — 2026-10-04

### Adicionado

- **Vínculo do participante nas listas de presença**: o nome passa a sair com o
  vínculo — alunos como `Nome (Aluno/Curso-Turma-Ano)` e os demais como
  `Nome (Vínculo)` — tanto na tela quanto no PDF de assinatura e nas
  exportações (CSV/Excel/PDF) da lista de presença.
- **Agrupamento e filtros na tela da lista de presença**: filtros independentes
  de vínculo, curso, turma, ano, presença e busca por nome/e-mail; e um
  agrupamento fixo de dois níveis (vínculo → curso · turma · ano) ligado por
  `?agrupar=1`, com cabeçalhos de grupo e ordenação por grupo e nome.
- **Três modos de impressão da folha de assinatura (PDF)**: `simples` (só
  nomes), `agrupada` (vínculo → curso/turma/ano, nome simples nas linhas) e
  `vinculo` (nome com o vínculo). Os botões "Listas de presença (PDF)" do
  evento, o PDF por atividade (na lista de atividades) e o ícone do cartão do
  dashboard viraram menus com as três opções (`?modo=`); `?agrupar=1` continua
  valendo como apelido de `agrupada`.

## [2.16.1] — 2026-10-03

### Corrigido

- **Crachás de equipe de apoio e co-organizadores**: o crachá é derivado de
  evento + pessoa + papel (`eventos/crachas.py`), e a regra só reconhecia o
  dono (`Evento.organizador`), os palestrantes e os inscritos. Por isso os
  **co-organizadores** (`Evento.organizadores`) e a **equipe de apoio**
  (`Evento.equipe`) não apareciam no PDF **"Imprimir crachás"** nem em
  **"Meus crachás"**. Agora o co-organizador sai com o papel **Organizador** e a
  equipe com o papel **Equipe de apoio** (novo, com filtro `?papel=equipe` na
  API e a opção **Só equipe de apoio** no menu de impressão). A ordem dos papéis
  passou a ser `organizador > palestrante > equipe > participante`; quem tem
  mais de um papel continua com **um** crachá mostrando todos, e o **principal**
  (usado no filtro) segue essa ordem.
- `Presenca.PAPEL_CHOICES` ganhou `equipe` (migration `0054`), para a presença
  registrada pela equipe de apoio não gravar um valor fora das escolhas.

## [2.16.0] — 2026-10-01

### Adicionado

- **Filtro por papel e escolha de modelo no PDF de crachás**: o endpoint
  `GET /api/v1/eventos/{id}/crachas.pdf` passa a aceitar dois parâmetros
  opcionais, aplicados **antes** da geração. `?papel=participante|palestrante|
  organizador|todos` recorta pelo papel **principal** da pessoa no evento (cada
  uma cai em um balde só); valor inválido devolve `400` e recorte vazio devolve
  `404`. `?modelo=etiqueta|classico` escolhe o layout; valor inválido devolve
  `400`. Sem parâmetros, o comportamento é o de antes (todos, modelo padrão).
  O nome do arquivo identifica o recorte (`crachas-<evento>-palestrante.pdf`).
- **"Só um papel" na tela de atividades**: o menu **"Imprimir crachás"** ganhou
  as opções **Só palestrantes**, **Só participantes** e **Só organizadores**,
  como links diretos para o PDF. É um filtro **transitório** — não altera o
  modelo do evento nem o cadastro — e usa a mesma regra da API. Filtro inválido
  avisa e volta para a tela; recorte sem ninguém avisa com o papel pedido, em
  vez de gerar PDF sem página.

## [2.15.0] — 2026-09-30

### Adicionado

- **Senha padrão das contas criadas pelo organizador**: campo **"Senha padrão"**
  no evento (na criação, pelo modal, e na edição), com botão **Gerar** (senha
  forte) e mostrar/ocultar. Vale para equipe de apoio, co-organizadores e
  palestrantes criados pelo organizador/co-organizador: a pessoa entra com essa
  senha e troca depois. Padrão do sistema: `@snct2026` (configurável por
  `SENHA_PADRAO` no ambiente; cada evento pode sobrescrever). Antes, equipe e
  co-organizador recebiam uma senha aleatória e os palestrantes nasciam sem
  senha utilizável.
- `settings.SENHA_PADRAO` e `Evento.senha_padrao` (migration `0053`). A senha
  fica **em texto puro de propósito** (é um valor compartilhado, reexibido para
  o organizador repassar) e **não** entra na auditoria nem na API.

### Corrigido

- **Nome completo salvo no primeiro campo**: ao salvar uma conta cujo
  `first_name` traz o nome completo e o `last_name` está vazio, o nome é
  dividido (1ª palavra → nome; resto → sobrenome), mesma regra de
  `roster.dividir_nome`. Era o que acontecia no modal de palestrante e no
  cadastro, em que o nome inteiro ia para `first_name` e o sobrenome ficava em
  branco. O rótulo do modal passou a ser **"Primeiro nome"**.

## [2.14.1] — 2026-09-29

### Corrigido

- **Cadastro de palestrante na atividade (modal)**: o botão “Salvar” voltou a
  fechar o modal e a dar retorno. O handler ainda tratava `#id_palestrantes`
  como `<select multiple>`, mas desde a 2.11.0 o campo é um checklist
  (`.pal-lista`); o `select.add(...)` lançava `TypeError` e abortava antes de
  fechar o modal e de mostrar a mensagem. Agora o palestrante novo entra
  **marcado no checklist** (com foto) e o retorno é **explícito**: sucesso em
  confirmação persistente e erro de validação em alerta **dentro do modal**
  (por campo), sem engolir falhas de rede.
- **CPF obrigatório no modal de palestrante**: o formulário já exigia o CPF
  (`blank=False`), mas o campo não estava marcado como obrigatório — agora está,
  alinhado à validação do `PalestranteForm`.
- `#msgcontainer` passou a ficar acima do modal/backdrop (z-index 1060), para o
  aviso não ficar escondido atrás dele.

## [2.14.0] — 2026-09-28

### Adicionado

- **Listas de presença em PDF (folha de assinatura)**: botão em cada atividade
  na tela de atividades e um no cartão do evento (dashboard). O PDF traz o
  cabeçalho (evento, atividade, horário, local, tipo) e uma tabela **Nome +
  Assinatura** em branco, **sem e-mail**. Duas rotas novas, com a permissão de
  gestão do evento:
  - `/organizador/lista-presenca/atividade/<id>/pdf` — uma atividade;
  - `/organizador/lista-presenca/evento/<id>/pdf` — todas as atividades
    **publicadas**, uma por página.
- Testes cobrindo autorização, conteúdo do PDF (nome presente, e-mail ausente),
  uma página por atividade e a presença dos botões nas duas telas.

### Alterado

- **Barra de ações da tela de atividades** (`/organizador/atividades_evento/<id>/`)
  reorganizada em grupos rotulados — Atividades · Presença e impressão ·
  Relatórios e certificados —, com o botão de listas de presença em destaque.
- **Tabela de atividades**: o botão **Editar** passou para a coluna `#` (ao lado
  do número) e as demais ações ficaram agrupadas — gestão (publicar/excluir) e
  presença (lista, PDF, QR e check-in) —, com o certificado à parte. A
  renumeração preserva o botão (o número é atualizado sem refazer a célula),
  inclusive ao ordenar e ao criar atividade em tempo real.

## [2.13.1] — 2026-09-28

### Corrigido

- **Moderação do blog**: organizadores e co-organizadores agora veem no índice
  do evento a fila de posts pendentes de todos os autores.
- **Imagens do blog**: extensão gravada é normalizada a partir do formato real;
  serving deriva o MIME pelo conteúdo e envia `nosniff`/`no-store`. Uploads
  limitam tamanho a 8 MB e dimensões a 40 MP (PNG/JPG/WEBP); capa antiga é
  removida ao substituir ou limpar.
- **Auditoria**: ações do Django Admin para aprovar/ocultar posts registram
  usuário, evento e ação na trilha.
- **Storage privado**: impede configurar `BLOG_PRIVATE_ROOT` dentro de
  `MEDIA_ROOT`, que é servido publicamente.
- **Testes**: 11 regressões cobrem fila de moderação, MIME de imagens, cache,
  limpeza de capas, limites de pixel, auditoria e configuração do storage.

## [2.13.0] — 2026-09-28

### Adicionado

- **Blog do evento** (novo app `blog`): cada evento ganha um espaço de
  histórias e fotos. Leitura pública; organizadores (dono/co-organizador/staff)
  publicam direto e moderam; participantes com inscrição **ou** presença no
  evento enviam posts que entram como **pendentes** até a aprovação. Editar um
  post já publicado exige nova curadoria (volta para pendente).
- **Imagens do blog privadas por padrão**: ficam fora do `MEDIA_ROOT`
  (`BLOG_PRIVATE_ROOT`, padrão `./ifeventos/blog_privado`, com volume próprio no
  `docker-compose.yml`) e só são liberadas pela view `blog.arquivo_privado`,
  conforme a visibilidade do post. Upload validado pelo Pillow (8 MB por
  arquivo, até 12 fotos por post).
- Link **“Blog do evento”** na página da programação (sempre visível, mesmo sem
  publicações) e moderação também pelo Django Admin (jazzmin). O app `blog` cria
  apenas tabelas novas — nenhum modelo existente foi alterado.

## [2.12.2] — 2026-09-27

### Corrigido

- **Equipe de apoio**: ao remover uma pessoa da equipe de um evento, a flag
  global `Participante.is_equipe` agora é sincronizada (sinal `m2m_changed` em
  `Evento.equipe`): ela **some** quando a pessoa sai da equipe de **todos** os
  eventos e **permanece** se ela ainda for equipe de outro. Vale para a tela do
  organizador e para o admin.

## [2.12.1] — 2026-09-27

### Corrigido

- **Horas exibidas em UTC (3h adiantadas)**: alguns textos formatavam o
  `datetime` (aware, em UTC) sem converter para o fuso local. Corrigidos:
  - a mensagem da **janela de presença do QR** (“A confirmação desta atividade
    abre …”), que aparecia no lugar errado no cartaz/`/p/<token>/` e nas telas de
    QR/check-in;
  - a mensagem de **conflito de horário** ao se inscrever;
  - os `__str__` de **Registro de auditoria** e **Presença cancelada**.
- Novo `eventos/tempo.local_legivel()` — fonte única para formatar data/hora no
  fuso local, evitando repetir o erro.

## [2.12.0] — 2026-09-27

### Adicionado

- **Tema do Django Admin (django-jazzmin 3.0.5)**: admin com sidebar, dark mode
  e a identidade do IFMG (verde institucional), busca no topo pelos modelos mais
  usados e ícones por modelo. Nada muda nos `ModelAdmin` existentes.
- **`Participante.atualizado_em`** (auto_now): a última alteração da conta,
  mostrada no detalhe do participante no admin.
- **Miniaturas no admin**: onde há imagem (Evento, Atividade, Participante e
  Assinante), a lista e o detalhe mostram uma **miniatura clicável** (abre a
  imagem original); a assinatura aparece também no formulário de configuração do
  certificado. O certificado ganhou um link **“Abrir PDF”**.

### Alterado

- **Admin de Participantes**: coluna **“Criado em”** (`date_joined`) e
  **`is_equipe`** na lista (mais recentes primeiro), filtros por papéis/situação,
  seção **readonly “Registro”** (criação, último login e última atualização) e
  **actions para alternar** membro da equipe, organizador, participante e
  palestrante (atualizam `atualizado_em` sem reprocessar a foto).

## [2.11.0] — 2026-09-27

### Alterado

- **Seleção de palestrantes com foto e em ordem alfabética**: o formulário de
  atividade (organizador) troca o `<select multiple>` por um **checklist com
  avatar + nome** (caixa rolável, lista em ordem alfabética). O campo mantém o
  mesmo `name` (`palestrantes`), então a validação continua igual.
- **Proposta do participante**: o seletor de palestrantes (busca + chips) passa a
  mostrar a **foto** ao lado do nome; o endpoint de busca devolve `foto`.

## [2.10.0] — 2026-09-27

### Adicionado

- **AuditorIA com diagnóstico** (página `/organizador/auditoria/`): além do chat,
  um botão **“Analisar agora”** (janela padrão de 7 dias) gera um relatório que
  **aponta causa provável e solução** dos problemas da trilha, em **cards por
  severidade** + tabela dos erros mais frequentes (com link para o admin).
  - **Sinais determinísticos** (`eventos/auditor_diagnostico.py`): erros
    agrupados por logger + **assinatura normalizada** (mostra recorrência),
    tendência/picos por dia, 4xx/5xx e marcos operacionais. Números do ORM.
  - **Playbooks** (`eventos/auditoria_playbooks.py`): causa/solução curadas para
    assinaturas conhecidas (engineio/websocket-client, `SynchronousOnlyOperation`,
    unicidade de inscrição/presença, e-mail, OpenAI, socket) + mapa loggers→módulo.
  - **Contexto de IA** `auditoria_diagnostico` (modelo configurável no admin); a
    IA só interpreta — com fallback **determinístico** se ela falhar.
  - O **chat** da auditoria passa a incluir causa provável e sugestão quando o
    resultado tem erros, e ganha **memória** (últimas ~6 mensagens) para encadear
    perguntas. Restrito ao superusuário; PII mascarada nos sinais.

## [2.9.1] — 2026-09-27

### Corrigido

- **Trilha de auditoria poluída por erro do Socket.IO**: o aviso
  `websocket-client package not installed, only polling transport is available`
  (do `engineio.client`) aparecia como **“Erro / Sistema”** na auditoria,
  atribuído ao usuário da requisição. Duas medidas: instalado o pacote
  **`websocket-client`** (o cliente passa a usar websocket em vez de só
  long-polling) e os loggers **`engineio`/`socketio`** saíram da auditoria — o
  erro deles vai só para o console (`docker logs`).

## [2.9.0] — 2026-09-27

### Adicionado

- **Cartazes de presença (PDF)**: o organizador gera, na lista de atividades, um
  PDF com **1 cartaz por folha A4** (21 × 29,7 cm, retrato) — um por atividade
  publicada, com a logo do IFMG e a imagem do evento, o título da atividade,
  evento/data/local e um **QR grande** para confirmar presença. É para imprimir e
  **fixar na porta da atividade**. O desenho segue o **modelo de crachá escolhido
  no evento** (etiqueta/clássico).
- O QR do cartaz é **permanente** (o da tela expira em minutos e não serve no
  papel): ele é assinado com um sal próprio e **vale só dentro da janela da
  atividade**, que já é a regra da presença. O identificador da atividade/QR
  rotativo e o do cartaz não se misturam.
- **Tolerância da presença por atividade**: o organizador define, em cada
  atividade (`margem_presenca_antes_min` / `margem_presenca_depois_min`), quanto
  tempo antes do início e depois do término a confirmação por QR é aceita; se a
  atividade não definir, vale a do evento (`Evento.margem_presenca_*`) e, se o
  evento também não definir, o padrão do sistema — agora **20 min antes / 20 min
  depois** (era 30 min / 2 h). O **cartaz imprime o intervalo exato** em que a
  confirmação é aceita (ex.: “Confirme de 23/09 07:40 às 09:20”).
- O botão **“Imprimir cartazes”** (renomeado de “Cartazes (PDF)”) abre um manual
  rápido (modal) antes de gerar o PDF: para que serve, o passo a passo e,
  principalmente, **quando o cartaz vale** — com os números reais do evento
  (quantas atividades, quantas folhas A4 e a faixa de horário aceita) e um atalho
  para ajustar os horários de tolerância.

## [2.8.0] — 2026-09-27

### Adicionado

- **Atividades sem inscrição** (`Atividade.exige_inscricao`, padrão `true`): o
  organizador (e o proponente) pode marcar uma atividade aberta — como um
  **LUAU** — em que a pessoa **só comparece**. Com a flag desmarcada, o número
  de vagas é ignorado e a tela mostra o selo **“Não precisa de inscrição”** no
  lugar das vagas, do botão *Inscrever* e do *Lotado* (programação pública,
  grade/cronograma, lista de disponíveis do participante e lista do
  organizador). A self-inscrição é recusada na tela, no AJAX e na API
  (`POST /api/v1/minhas-inscricoes/`), e o campo aparece na leitura/escrita de
  `atividades/` e `propostas/`. O check-in por crachá continua valendo, então a
  atividade ainda pode emitir certificado por presença.

## [2.7.2] — 2026-09-24

### Alterado

- **Menu do avatar**: os itens de **certificados, propostas, palestras e crachás**
  só aparecem quando há conteúdo para o usuário (antes ficavam sempre visíveis).
  Rótulos ajustados para **“Meus certificados”**, **“Minhas propostas”** e
  **“Meus crachás”** (e **“Minhas palestras”**, inalterado).

## [2.7.1] — 2026-09-24

### Adicionado

- Menu do usuário: link para o **`/admin/`** quando o usuário é `is_staff`
  (abre em nova aba).
- **Contextos de IA como ponto único de configuração** (documentado em `IA.md`):
  o `entrypoint` passa a rodar `sincronizar_contextos_ia` a cada start, então
  contextos novos (ex.: o do agente **AuditorIA**) aparecem no admin já após o
  deploy, prontos para escolher o modelo e **habilitar/desabilitar**.

## [2.7.0] — 2026-09-24

### Adicionado

- **Trilha de auditoria** (`RegistroAuditoria`, append-only, somente leitura no
  admin): registra **quem fez o quê, quando e onde** — criar/editar/excluir das
  entidades editoriais (evento, atividade, espaço, vaga, chamada), criar
  inscrição/presença, login/logout, emissão de certificado, configuração de
  certificado, decisão de proposta e cancelamento de presença. CPF/e-mail são
  mascarados nos detalhes.
- **Log de contêiner com rotação** (`json-file`, 10 MB × 5) no `docker-compose`,
  para os tracebacks de erro persistirem e serem pesquisáveis.
- **API da auditoria** (`/api/v1/auditoria/`, somente leitura) com filtros e a
  ação `resumo/` (agregações por ação/entidade/origem/dia), pensada para consulta
  por pessoas e por **agentes de IA/MCP**. E-mail do usuário mascarado.
- **Agente interno "AuditorIA"** (`/organizador/auditoria/`): perguntas em
  linguagem natural sobre o histórico, respondidas por IA a partir de uma consulta
  estruturada validada e executada no ORM (sem text-to-SQL).
- **Captura de erros na auditoria**: handler de logging grava ERROR+ como
  `acao="erro"` (com traceback). **Sentry** opcional via `SENTRY_DSN`.
- Comando **`limpar_auditoria`** (retenção; dry-run por padrão).

## [2.6.0] — 2026-09-24

### Adicionado

- **Catálogos de modelos do certificado** na tela de configuração:
  - **modelos `.docx`** por tipo (evento/atividade), com lista, seleção, upload e
    remoção por AJAX; o arquivo sai como `template_<escopo>_<uuid>.docx`;
  - **imagens de fundo** do modo texto, com lista (com miniatura), seleção, upload
    e remoção por AJAX.
- Comando `limpar_arquivos_certificado` para remover arquivos órfãos (modelos
  `.docx` e fundos): dry-run por padrão, `--confirmar` para apagar.

### Corrigido

- Comentário de template `{# … #}` em várias linhas vazava como texto no
  dashboard do organizador e na tela de propostas (trocado por `{% comment %}`).

## [2.5.0] — 2026-09-23

### Adicionado

- **Área de certificados do organizador.** Duas configurações por evento (abas
  **Certificado do evento** e **Padrão das atividades**), mais um **override por
  atividade** — a atividade usa o padrão do evento até você personalizar a dela.
  Cada config define:
  - **conteúdo**: título, corpo com variáveis e rodapé;
  - **layout** (dois formatos): **texto livre** (com **imagem de fundo
    opcional**) ou **modelo `.docx`** com tags (`{{nome}}`, `{{tipo_atividade}}`,
    `{{atividade}}`, `{{evento}}`, `{{carga_horaria}}`, `{{data}}`, `{{local}}`,
    `{{qr}}`, `{{assinatura1}}`/`{{assinatura2}}`);
  - **assinaturas** (1 ou 2) escolhidas de um **catálogo de assinantes**
    reutilizável (organizador e staff), com imagem (snapshot no certificado);
  - **carga horária** e **percentual mínimo de presença** do evento.
- **Carga horária** por atividade e por evento; **percentual do evento**
  configurável (antes: 75% fixo no código).
- **Elegibilidade correta**: certificado de **atividade** = a atividade emite
  certificado e a pessoa participou (presença; fallback inscrição confirmada);
  certificado de **evento** = presença mínima nas atividades que emitem
  certificado.
- **Entrega** na área do participante **e** por **e-mail com o PDF anexo**
  (configurável por config).
- **Pré-visualização** do certificado em PDF, por escopo (evento/atividades/atividade).
- **Botões de emissão**: **“Emitir certificados do evento”** (na tela de
  configuração, na tela de atividades e no card do dashboard) e **“Emitir
  certificados de todas as atividades”** (aba de atividades). O e-mail segue a
  opção “Enviar por e-mail” da configuração.
- **Tela “layout-primeiro”**: dois formatos — **texto livre** (com **imagem de
  fundo opcional**) e **modelo `.docx`** — e a tela mostra **só os campos que o
  formato usa**. No `.docx`, o conteúdo e as assinaturas ficam no arquivo (a tela
  não os pede).
- **Certificado do evento usa o percentual de participação** no texto
  (`{{percentual_participacao}}`, ex. `80%`, e `{{percentual_minimo}}`) — **sem
  carga horária** no evento. `{{carga_horaria}}` é do certificado de atividade e,
  quando não informada, é **calculada pelo horário** (fim − início).
- **QR maior** no canto inferior direito e a **URL de confirmação em uma linha
  abaixo do rodapé, clicável** (nos modos texto e imagem); no `.docx`, `{{qr}}`
  (imagem) e `{{qr_url}}` (texto).

### Corrigido

- **Admin**: adicionada a busca em **Eventos** e **Participantes** e **corrigida**
  a busca de **Atividades**, **Inscrições** e **Certificados** (usavam um FK
  direto em `search_fields`, que estoura `FieldError` — o "Search" daria 500).
- **`Certificado.__str__`** não quebra mais quando o registro não tem atividade
  nem evento (certificado antigo/incompleto derrubava a lista do admin).
- **Certificado `.docx` não cai mais no layout antigo em silêncio**: se a
  conversão para PDF falhar (ex.: LibreOffice indisponível), a pré-visualização e
  a emissão **informam o erro** e **não** geram um certificado fora do modelo. Na
  emissão em lote, o que falha é pulado e relatado (`falhas`).

### Notas

- Novos modelos: `Assinante`, `ConfiguracaoCertificado` (com escopo evento/atividade)
  e `AssinaturaCertificado`; novos campos em `Evento`/`Atividade`/`Certificado`
  (migrations `0040`, `0041`, `0042`).
- O modo `.docx` usa **LibreOffice** na imagem (build maior) e `docxtpl`; sem o
  LibreOffice, o render cai no modo fundo (não quebra a tela).

## [2.4.0] — 2026-09-23

### Adicionado

- **Avatar e nome do Google no primeiro acesso.** Ao entrar pelo Google, o
  sistema aproveita o que já vem no perfil do provedor (`extra_data`):
  - **avatar**: baixa a `picture` uma vez, recorta no centro e salva em
    `Participante.foto` (256 px). Se o download falhar, guarda a URL em
    `Participante.foto_social_url` e `get_foto_url()` usa como fallback;
  - **nome**: preenche `first_name`/`last_name` **só quando estiverem vazios**.

  Nunca sobrescreve foto/nome já definidos e nunca quebra o login (falhas são
  registradas e ignoradas). Cobre o cadastro social novo (adapter) e o
  auto-connect de conta existente (signals `social_account_added`/`_updated`).

### Notas

- Novo campo `Participante.foto_social_url` (migration `0039`).

## [2.3.2] — 2026-09-23

### Corrigido

- **A pré-carga (planilha) agora completa o perfil no primeiro ACESSO, não só na
  criação da conta.** Contas pré-cadastradas (importação em lote, com senha
  inutilizável) e o *auto-connect* do Google passam a receber os
  metadados/CPF/nome da planilha no primeiro login (`user_logged_in`), uma única
  vez. Antes, quem já tinha conta quando a planilha foi importada nunca era
  completado — a rotina só rodava no `user_signed_up`. Era o caso de contas
  criadas em lote em 14/09 com a planilha importada depois.
- **Placeholder de palestrante** (sugestão convertida e `POST /palestrantes/`)
  também passa pela pré-carga na criação, quando o e-mail está na planilha.

### Adicionado

- **Comando `completar_roster`** — aplica a planilha nas contas existentes
  (`--dry-run`, `--email`), para resolver o passivo de pré-cadastros. É ação de
  dados: executar em produção **somente com autorização**.

### Alterado

- **E-mail "conta já existe"** ganhou texto próprio em PT-BR explicando que o
  e-mail tem pré-cadastro e as duas saídas (entrar com o Google ou redefinir a
  senha). Mantém a proteção contra enumeração.

## [2.3.1] — 2026-09-22

Correções e endurecimentos encontrados pela suíte por requisitos
(`tests_requisitos/`). Um item é **mudança de contrato documentada** (ver
"Alterado").

### Corrigido

- **E-mail não vaza mais no catálogo público** (`GET /eventos/`,
  `/eventos/{id}/`, `/atividades/`): o `email` do organizador, dos palestrantes
  e do proponente agora só sai para o próprio, organizador ou staff. As leituras
  já organizer-scoped (inscrições, presenças, certificados, MCP) continuam
  trazendo o e-mail.
- **Detalhe público do evento não expõe mais rascunho nem proposta pendente**:
  o campo `atividades` passou a usar a mesma regra da listagem
  (`eventos.regras.atividades_publicas`) — antes só a listagem filtrava.
- **Grade em lote herda a capacidade do espaço**: `POST /eventos/{id}/vagas/gerar/`
  sem `capacidade` criava vagas com capacidade 1; agora usa a capacidade
  sugerida de cada `Espaco`.
- **Presenças e vagas com escopo por evento**: `GET /presencas/` exige
  organizador/co-organizador/equipe (não mais qualquer autenticado) e o
  `get_queryset` só devolve eventos em que a pessoa atua; `GET /vagas/?evento=`
  nega organizador **sem vínculo** com o evento (o proponente continua lendo a
  grade).
- **Ações globais do organizador exigem o papel**: `/organizador/dashboard/` e
  `/organizador/metadados/modelo.csv` devolvem **403** a quem não é
  organizador/superuser (antes: 200 e 302).
- **Emissão de crachá não quebra com `MEDIA_ROOT` string**: `arquivo_logo_cracha`
  normaliza com `Path(settings.MEDIA_ROOT)` (antes, `str / str` → 500).

### Segurança

- **Limite de tentativas de login**: `POST /auth/token/` ganhou throttle
  (`ScopedRateThrottle`, escopo `login`, 10/min) e o login web ganhou
  `ACCOUNT_LOGIN_ATTEMPTS_LIMIT`/`TIMEOUT` do allauth. Antes, 10 senhas erradas
  não mudavam nada.

### Alterado

- **Edição de proposta pelo organizador (mudança de contrato documentada)**:
  `PATCH /propostas/{id}/` é permitido ao **autor** (pendente, chamada aberta)
  **ou ao organizador do evento** (dono/co-organizador). A decisão de mérito
  segue em `aprovar`/`rejeitar`. Documentado em `API.md`.

### Documentação

- `API.md`: matriz de permissões por persona, origens dos três códigos de
  check-in, escopo de `/vagas/`, capacidade da grade e o PATCH de proposta.
- `BACKLOG.md`: regra de decisão de proposta alinhada ao escopo por evento (2.3.0).

## [2.3.0] — 2026-09-21

### Adicionado

- **Co-organizadores por evento**: um organizador que **não é o dono** do evento
  pode ser adicionado para **gerenciá-lo** (atividades, relatórios, equipe de
  apoio, edição do evento). O **dono** continua sendo o principal (excluir o
  evento é só dele). O organizador gerencia a lista na tela de edição do evento
  ("Co-organizadores"), adicionando por e-mail (conta existente é
  reaproveitada e ganha `is_organizador`; e-mail novo cria uma conta mínima de
  organizador com senha temporária).
- **Permissão por escopo de evento**: `pode_gerenciar_evento` agora vale para
  dono **ou** co-organizador (staff/superuser sempre). A flag `is_organizador`
  sozinha **deixa de dar acesso a qualquer evento** — o dashboard lista os
  eventos que a pessoa é dona/co-organizadora. Organizadores sem vínculo com um
  evento não o veem nem operam.

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
