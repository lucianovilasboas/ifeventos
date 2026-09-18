# BACKLOG — Nossos Eventos (IF Eventos)

Pendências combinadas e ainda **não** feitas, para consulta futura.
Atualizado em **18/09/2026** · `main` em `a8d2900` (= `origin/main`) · working tree limpo · **492 testes OK**. API da chamada mergeada, publicada **e deployada em produção**.

> Como este projeto trabalha: branch nova a partir da `main` → implementar → rodar a suíte
> (`docker exec app_django bash -lc 'cd /ifeventos && python manage.py test -v 1'`) → **parar**
> e aguardar autorização antes de commit/merge/push.

## 1. Bloqueadas (dependem de operação, não de código)

- **Ligar os avisos por e-mail da chamada em produção.** Hoje `PROPOSTAS_NOTIFICAR_EMAIL=False`
  (padrão) — nada é enviado. Para ligar: preencher `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` e
  `DEFAULT_FROM_EMAIL` no `ifeventos/.env`, pôr `PROPOSTAS_NOTIFICAR_EMAIL=True` e
  `docker compose up -d`. Fazer um **envio controlado** (criar uma proposta e ver se chega); se não
  chegar, `docker compose logs app | grep -i smtp`. O envio é *best-effort*: nunca derruba a ação.
- **Convite a palestrante que ainda não tem conta.** Último item da chamada: criar a conta com senha
  inutilizável + `EmailAddress(verified=True)` (o convite chegou naquele endereço) e enviar o link de
  definição de senha do allauth. **Só entra depois do SMTP validado.** Ressalvas: entregabilidade
  (spam), contas criadas por terceiros e limite de convites por proposta.

## 2. Deploy — procedimento (última execução: 18/09/2026, feita)

Produção (`ovm-1` → `/opt/docker/ifeventos`, container **`ifeventos_app`**) está com a API da chamada
no ar. O lote deployado **não tem migration**: é só `git pull` + rebuild, sem passo de banco.

Para as próximas vezes:
1. backup do banco (há um `backup_*.sql` no próprio diretório);
2. `cd /opt/docker/ifeventos && git pull && docker compose up -d --build`;
3. conferir o topo da `main` (`git log --oneline -1`), `/api/v1/docs/` abrindo e o site normal
   (home, programação, dashboards). O e-mail deve continuar **desligado** (flag desligada).

### Verificação pós-deploy (roteiro)

Ao **reiniciar o MCP**, o `server.py` atualizado passa a expor as 19 tools da chamada
(`obter_chamada`, `configurar_chamada`, `gerar_grade_vagas`, `criar/aprovar/rejeitar_proposta`, ...).
Até lá, a sessão em curso continua com as 34 antigas (o cliente guarda a lista do início da sessão).

**Produção** (VM `ovm-1`, container `ifeventos_app`):
- `git log --oneline -1` em `/opt/docker/ifeventos` deve mostrar o **topo da `main`** (`a8d2900`
  quando este roteiro foi escrito; se houver commit novo, será ele — o repo de prod pode ficar
  atrás só em commits de doc, que não exigem rebuild).
- HTTP com o token de serviço de prod: `/eventos/`, `/docs/`, `/espacos/`, `/propostas/` → 200;
  `/eventos/<id>/chamada/` → 200 com `aberta_agora` (ou 404 "sem chamada" — JSON, não HTML de rota
  inexistente).
- Site: home, `/eventos/`, dashboards; o e-mail continua **desligado**.
- MCP de prod (só leitura): `listar_espacos`, `listar_vagas(evento_id)`, `obter_chamada(evento_id)`,
  `listar_propostas(evento_id)`.

**Dev** (depois de reiniciar o MCP): ciclo descartável evento → chamada → espaço → grade (rodar 2×, a
segunda idempotente) → proposta → painel → aprovar (rejeitar já decidida → **400**) → remover →
excluir tudo; conferir `count=0` no fim. **NUNCA usar o evento 107** (SNCT 2026, tem dados reais).

**Rollback** (o lote não tem migration): `git reset --hard 82a1634 && docker compose up -d --build`.

## 3. Operação no servidor (quando fizer sentido)

- `python manage.py limpar_metadado siape --aplicar` — se ainda não rodou em produção.
- `MAX_PROPOSTAS_POR_PROPONENTE=<n>` no `.env` — para ligar o limite de propostas por pessoa
  (hoje `0` = sem limite).
- `python manage.py sincronizar_locais --de "Nome antigo" --para "Nome novo"` — **dry-run primeiro**;
  só se forem padronizar nomes de espaço (o `local` das atividades é texto, não FK).

## 4. Código — melhorias menores que ficaram na conversa

| Item | O que é | Tamanho |
|---|---|---|
| Badge em tempo real nas outras telas | Hoje só o dashboard do organizador reage ao socket; a tela da chamada e a fila de propostas poderiam atualizar também | pequeno |
| Admin com inlines | Vagas dentro do Evento (e/ou da Chamada) em vez de registros soltos | pequeno |
| Gráficos no painel da chamada | Hoje são KPIs/tabelas; dá para acrescentar Chart.js (donut de status, ocupação por espaço) | pequeno/médio |
| Grade: excluir vagas em lote e salvar "layouts" | Complementos do gerador de grade | médio |
| MCP das propostas | Expor a chamada no servidor MCP (a API já está pronta) | médio |
| Convite a palestrante | Ver seção 1 | médio |

## 5. Notas técnicas / armadilhas (para não tropeçar de novo)

- **Produção**: container `ifeventos_app` (o `app_django` é do **dev**). Deploy
  `git pull && docker compose up -d --build`; as migrations rodam no `entrypoint`
  (a menos que `SKIP_MIGRATE=1` esteja no `.env`).
- **`socket_server.py` tem um handler explícito por evento**: evento novo **sem handler é descartado
  em silêncio**. Ao criar um aviso novo, adicione o handler lá (e o listener na tela).
- **Testar socket não funciona via `manage.py shell`**: o processo sai antes do emit chegar.
  Teste pelo fluxo real no navegador (duas abas, ou aba + outra sessão).
- **allauth 65.19.2**: `ResetPasswordForm` **não** marca o e-mail como verificado. Com
  `ACCOUNT_EMAIL_VERIFICATION='mandatory'`, um convite precisa criar a conta já com `verified=True`.
- **`local` da atividade é texto** (copiado na criação/proposição): renomear o espaço no catálogo não
  alcança o que já existe — use `sincronizar_locais`.
- **`includes/agenda_grade.html` é COMPARTILHADO** (programação pública, painel do participante e
  grade do organizador): recurso exclusivo do organizador entra por **parâmetro do include**
  (`mostrar_acoes`), nunca direto no partial.
- **A grade de vagas da proposta não tem dados próprios**: ela lê as `<option>` do select (por isso
  acompanha sozinha o que o servidor libera). Mexeu nas opções? A grade acompanha sem tocar no JS.
- **Linhas de grade (visual)**: `--border` (#e5e5e5) **some** sobre `--surface` (#f7f7f7) — para a
  malha da grade de vagas foi criada a variável local `--grade-linha` (#d9d9d9).
- **Texto longo em elemento `nowrap` alarga o DOCUMENTO** e desloca topbar (`sticky`) e bottomnav
  (`fixed`), que passam a medir a largura do layout. Teto de largura (`max-width: 100%`) + quebra
  resolvem (ver `.chip-evento` e o precedente `.app-hero .chip`). Há uma guarda em
  `.app-content-top { overflow-x: clip }` — prefira `clip` a `hidden` (não cria contêiner de rolagem,
  então não quebra `sticky` nem as áreas com `overflow-x: auto`).
- **Quem decide proposta é qualquer `is_organizador`**, não só o dono do evento (regra do site,
  `eventos.crachas.pode_gerenciar_evento`). A API espelha isso — de propósito: o token de serviço do
  MCP não é dono dos eventos. Editar **conteúdo** (evento, atividade, vaga) é que é do dono.
- **Dev local** (não é produção): o evento 107 (SNCT 2026) está com **160 vagas** e **1 proposta
  pendente** de teste. Não apagar.

## 6. Fechado recentemente (para não reabrir)

- **API da chamada em produção (18/09/2026)**: deploy do lote da API (F1, F3, F4, F2 da chamada,
  `API.md` e o fix da decisão terminal) na VM `ovm-1`, **sem migration**. Verificado: `/api/v1/`
  `eventos`, `docs`, `espacos`, `propostas` → 200; `obter_chamada(14)` com `aberta_agora=true`
  (79 vagas livres) e as tools `mcp-eventos-prod_*` respondendo (painel do evento 14 com 80
  vagas / 79 livres e 2 propostas). Em dev, o ciclo completo da chamada foi testado pelas tools
  novas do MCP, com os dados temporários removidos no fim.
- **API REST da chamada de proposições (F2)**: janela (`GET/PUT /eventos/{id}/chamada/`), painel
  (`/painel-chamada/`), catálogo de espaços, grade de vagas (com geração em lote idempotente),
  propostas (propor/editar/cancelar/aprovar/rejeitar) e `vaga` opcional no POST de atividade —
  tudo delegando a `eventos.propostas` (regra única). Documentada em `API.md`. Antes disso, F1 (ciclo
  rascunho/proposta na leitura), F3 (conflito único + schema limpo) e F4 (presença, crachá, QR,
  verificação e permissões de escrita).
- **Grade do organizador**: **Editar** e **Excluir** direto nos chips (`includes/agenda_grade.html`
  ganhou o parâmetro `mostrar_acoes`, ligado só por essa tela) e o botão **"Ocupação por sala" saiu**
  da tela de atividades (continua no cartão do evento, no dashboard).
- **Campo "Dia, horário e espaço" da proposta** com **alternador Lista/Grade**: a grade (dias ×
  horários, célula = espaço + capacidade) é montada por JS a partir das opções do próprio select —
  escolher na grade seleciona a opção, e só aparecem vagas livres por construção.
- **Chamada de proposições de atividades**: período (abrir/encerrar), grade de vagas com reserva
  *first-come*, proposta como rascunho pendente, aprovação/rejeição com motivo, banner na home,
  "Minhas propostas", sugestão de tipo com IA, **gerador de grade em lote**, **painel de
  acompanhamento**, **editar vaga** (com trava quando há proposta ativa), **catálogo de espaços
  reaproveitado** (semeado a partir dos locais das atividades, com busca e edição), **limite de
  propostas por pessoa** (`MAX_PROPOSTAS_POR_PROPONENTE`, desligado por padrão), **aviso por e-mail**
  (desligado por padrão) e **busca de palestrante** entre os cadastrados.
- **Tempo real**: contador de propostas pendentes no cartão do evento (socket) e filtro de evento em
  **chips** no painel do participante.
- **Correção do "+N no mesmo horário"** no celular (grade do organizador e painel do participante).
- **Filtro `publicada` na API** (rascunhos e propostas deixaram de vazar para leitura anônima).
- **SIAPE removido** dos metadados (Servidor passou a ter só Função) + comando `limpar_metadado`.
- **Botão "Ver programação"** direto no card do evento em `/eventos/`.
- **Relatórios gráficos** do evento e **ocupação por salas** (com cartões no mobile e "Voltar" dinâmico).
