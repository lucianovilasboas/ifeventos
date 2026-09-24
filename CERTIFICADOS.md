# Certificados — guia do organizador

O certificado tem **duas configurações por evento**:

- **Certificado do evento** — usado no certificado de quem cumpre o percentual mínimo de presença.
- **Padrão das atividades** — usado nos certificados das atividades que **não** tiverem
  configuração própria.

Cada atividade pode ter a **sua configuração** (um *override*): na aba “Padrão das
atividades” há a lista das atividades que emitem certificado; em **Configurar** você
personaliza (ou usa **“Usar o padrão do evento”** para voltar).

Telas: `/organizador/certificado/<evento_id>/config/evento/`,
`/organizador/certificado/<evento_id>/config/atividades/` e
`/organizador/certificado/atividade/<atividade_id>/`. O **catálogo de assinantes**
fica em `/organizador/assinantes/` (organizador e staff).

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

## Variáveis do texto/template

| variável | valor |
| --- | --- |
| `{{nome}}` | nome completo da pessoa |
| `{{cpf}}` | CPF (só os dígitos) |
| `{{tipo_atividade}}` | tipo da atividade (ex.: Oficina) |
| `{{atividade}}` | título da atividade (vazio no certificado do evento) |
| `{{evento}}` | título do evento |
| `{{carga_horaria}}` | carga da atividade (`2h`, `1h30`…) — **vazio no evento** |
| `{{percentual_participacao}}` | % que a pessoa atingiu no evento (ex.: `80%`) — só no evento |
| `{{percentual_minimo}}` | % exigido pelo evento (ex.: `75%`) — só no evento |
| `{{data}}` | data de emissão (`dd/mm/aaaa`) |
| `{{local}}` | local da atividade ou do evento |
| `{{qr}}` | imagem do QR de verificação (só no modo `.docx`) |
| `{{qr_url}}` | URL de verificação (texto) — só no modo `.docx` |
| `{{assinatura1}}` / `{{assinatura2}}` | imagem da assinatura (só no modo `.docx`) |
| `{{assinante1}}` / `{{cargo_assinante1}}` | nome/cargo do assinante (e 2) |

No modo **texto livre**, use as variáveis de texto (o QR e as assinaturas são
desenhados automaticamente; o QR fica no canto inferior direito e a **URL de
confirmação sai em uma linha abaixo do rodapé, clicável**). No modo **`.docx`**,
todas funcionam, inclusive as imagens.

## Elegibilidade

- **Atividade**: a atividade precisa ter **“emite certificado”** marcado e a pessoa
  precisa ter **presença** (ou inscrição confirmada).
- **Evento**: presença mínima configurada, contando só as atividades que emitem
  certificado.

## Emissão

- Por inscrição, por atividade (todos os elegíveis) ou por evento (todos com o
  percentual mínimo) — nas telas atuais de certificados.
- Idempotente: não gera de novo o que já existe.
- Verificação pública pelo QR: `/c/<token>/`.
