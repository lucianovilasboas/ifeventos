# Certificados — guia do organizador

O certificado tem **configurações por evento**:

- **Certificado do evento** — usado no certificado de quem cumpre o percentual mínimo de presença.
- **Padrão das atividades** — usado nos certificados das atividades que **não** tiverem
  configuração própria.
- **Certificados de função** — um por grupo: **organizadores**, **palestrantes**,
  **equipe de apoio** e **comissão organizadora**.

Cada atividade pode ter a **sua configuração** (um *override*): na aba “Padrão das
atividades” há a lista das atividades que emitem certificado; em **Configurar** você
personaliza (ou usa **“Usar o padrão do evento”** para voltar).

Telas: `/organizador/certificado/<evento_id>/config/<escopo>/`, onde `escopo` é
`evento`, `atividades` ou o código da função (`organizador`, `palestrante`,
`equipe`, `comissao`); e `/organizador/certificado/atividade/<atividade_id>/`.
O **catálogo de assinantes** fica em `/organizador/assinantes/` (organizador e staff).

## O que se configura

A tela começa pelo **Layout** (dois formatos) e mostra **só o que ele usa**:

- **Texto livre** — você escreve o conteúdo (título, texto, rodapé) e escolhe as
  assinaturas. A **imagem de fundo é opcional**: com imagem, o texto e as
  assinaturas são desenhados por cima; sem imagem, o certificado usa o fundo
  padrão.
- **Modelo `.docx`** — você envia um documento do Word com as tags. **O conteúdo
  e as assinaturas ficam dentro do arquivo** (por isso a tela não mostra os
  campos de texto nem a lista de assinaturas). Requer LibreOffice no servidor
  (já previsto no `Dockerfile`).

Comuns a todos os escopos:

- **Assinaturas (1 ou 2)** — no modo **texto livre**: escolhidas do **catálogo**.
  A imagem do assinante é copiada (snapshot), então trocar o catálogo depois não
  muda certificados já configurados.
- **Enviar por e-mail** — manda o PDF em anexo ao participante.

Por **escopo** (aba):

- **Evento**: **presença mínima (%)** — quanto o aluno precisa comparecer, entre
  as atividades que **emitem certificado**, para ganhar o certificado do evento
  (padrão 75%). **Não há carga horária no certificado do evento** (o texto usa o
  percentual de participação).
- **Atividade**: **carga horária padrão** (opcional). Sem ela, a carga é
  calculada pela **diferença entre o horário final e o inicial** da atividade
  (`2h`, `2h30`, `45min`).
- **Função** (organizador/palestrante/equipe/comissão): **sem carga horária e sem
  percentual** — o texto usa `{{funcao}}`.

## Variáveis do texto/template

| variável | valor |
| --- | --- |
| `{{nome}}` | nome completo da pessoa |
| `{{primeiro_nome}}` / `{{sobrenome}}` | nome e sobrenome |
| `{{cpf}}` | CPF (só os dígitos) |
| `{{cpf_mascara}}` | CPF formatado (`000.000.000-00`) |
| `{{email}}` / `{{telefone}}` | contato da pessoa |
| `{{funcao}}` | função do certificado: Organizador(a), Palestrante, Equipe de apoio ou Comissão organizadora (vazio nos certificados de atividade/evento) |
| `{{evento}}` | título do evento (alias `{{evento_nome}}`) |
| `{{evento_local}}` | local do evento |
| `{{evento_data_inicio}}` / `{{evento_data_fim}}` | datas (`dd/mm/aaaa`) |
| `{{evento_periodo}}` | período do evento (ex.: `10 a 12/10/2026`) |
| `{{evento_categoria}}` | categoria do evento |
| `{{evento_descricao}}` | descrição do evento |
| `{{evento_carga_horaria}}` | carga horária padrão do evento |
| `{{organizador}}` | nome do organizador |
| `{{atividade}}` | título da atividade (vazio no evento) (alias `{{atividade_nome}}`) |
| `{{tipo_atividade}}` | tipo da atividade (ex.: Oficina) (alias `{{atividade_tipo}}`) |
| `{{atividade_local}}` / `{{local}}` | local da atividade / local resolvido (atividade ou evento) |
| `{{atividade_data}}` / `{{atividade_hora_inicio}}` / `{{atividade_hora_fim}}` | data e horários |
| `{{atividade_inicio}}` / `{{atividade_fim}}` | início/término (`dd/mm/aaaa HH:MM`) |
| `{{atividade_periodo}}` | ex.: `10/10/2026 08:00 às 10:00` |
| `{{atividade_descricao}}` / `{{atividade_palestrantes}}` | descrição / palestrantes |
| `{{carga_horaria}}` | carga da atividade (`2h`, `1h30`…) — **vazio no evento e na função**; **no palestrante é a carga TOTAL somada** |
| `{{atividades_lista}}` | **só palestrante**: uma linha por atividade — `- Tipo: Título, com carga horária 1h30 (10/10/2026);` |
| `{{atividades_texto}}` | **só palestrante**: texto corrido agrupado por tipo — `2 Palestras (Título A; Título B) e 1 Minicurso (Título C)` |
| `{{atividades_resumo}}` | **só palestrante**: resumo por tipo (ex.: `2× Palestra, 1× Minicurso`) |
| `{{n_atividades}}` | **só palestrante**: quantidade de atividades |
| `{{carga_horaria_total}}` | **só palestrante**: carga total somada (igual a `{{carga_horaria}}` no palestrante) |
| `{{percentual_participacao}}` | % que a pessoa atingiu no evento (ex.: `80%`) — só no evento |
| `{{percentual_minimo}}` | % exigido pelo evento (ex.: `75%`) — só no evento |
| `{{data}}` | data de emissão (`dd/mm/aaaa`) (alias `{{data_emissao}}`) |
| `{{hora_emissao}}` | hora de emissão (`HH:MM`) |
| `{{meta_<chave>}}` | metadado do participante (ex.: `{{meta_curso}}`, `{{meta_turma}}`) |
| `{{qr}}` | imagem do QR de verificação (só no modo `.docx`) |
| `{{qr_url}}` | URL de verificação (texto) |
| `{{assinatura1}}` / `{{assinatura2}}` | imagem da assinatura (só no modo `.docx`) |
| `{{assinante1}}` / `{{cargo_assinante1}}` | nome/cargo do assinante (e 2) |

No modo **texto livre**, use as variáveis de texto (o QR e as assinaturas são
desenhados automaticamente; o QR fica no canto inferior direito e a **URL de
confirmação sai em uma linha abaixo do rodapé, clicável**). O editor traz um
seletor **“Inserir variável”** com a lista completa. No modo **`.docx`**, todas
funcionam, inclusive as imagens.

### Certificado do palestrante (agregado)

O certificado de **função palestrante** é **um só para todas as atividades** da
pessoa no evento: ele lista cada atividade (`{{atividades_lista}}`, no formato
`- Tipo: Título, com carga horária 1h30 (10/10/2026);`), traz um **texto corrido**
agrupado por tipo (`{{atividades_texto}}`, ex.: `2 Palestras (Título A; Título B)
e 1 Minicurso (Título C)`) e soma a carga horária total (`{{carga_horaria}}`).
No `.docx` dá para percorrer a lista com `{% for a in atividades %}` (cada item
tem `titulo`, `tipo`, `carga_horaria`, `carga_minutos`, `data`). O palestrante
**continua** podendo receber o certificado por atividade, se tiver presença.

## Elegibilidade

- **Atividade**: a atividade precisa ter **“emite certificado”** marcado e a pessoa
  precisa ter **presença** (ou inscrição confirmada).
- **Evento**: presença mínima configurada, contando só as atividades que emitem
  certificado.
- **Função**: bastar o **vínculo** com o evento — organizador (dono + co-organizadores),
  palestrante (das atividades), equipe de apoio ou comissão organizadora. Não exige presença.

## Emissão

- Por inscrição, por atividade (todos os elegíveis), por evento (todos com o
  percentual mínimo) ou por função (todos de um grupo, ou individualmente) — nas
  telas de certificados.
- A **comissão organizadora** é uma lista do evento (em **Editar evento**), sem
  poderes de gestão.
- Idempotente: não gera de novo o que já existe; uma pessoa pode ter certificados
  de funções diferentes (ex.: organizador **e** palestrante).
- Verificação pública pelo QR: `/c/<token>/`.
