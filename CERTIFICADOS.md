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

- **Conteúdo**: título, corpo e rodapé. O corpo aceita variáveis entre `{{ }}`.
- **Aparência** (um modo):
  - **Só texto** — o texto é impresso no fundo padrão do sistema.
  - **Imagem de fundo** — envie uma imagem (PNG/JPG); o texto, as assinaturas e o
    QR são desenhados por cima.
  - **Modelo `.docx`** — envie um documento do Word com as tags; o layout é livre.
    Requer LibreOffice no servidor (já previsto no `Dockerfile`).
- **Assinaturas (1 ou 2)**: escolhidas do **catálogo**. A imagem do assinante é
  copiada para o certificado (snapshot), então trocar o catálogo depois não muda
  certificados já configurados.
- **Carga horária**: por atividade; se vazia, a da configuração, senão a do evento.
- **Presença mínima (%)** (só na config do evento): quanto o aluno precisa
  comparecer, entre as atividades que **emitem certificado**, para ganhar o
  certificado do evento. Padrão 75%.
- **Enviar por e-mail**: manda o PDF em anexo ao participante.

## Variáveis do texto/template

| variável | valor |
| --- | --- |
| `{{nome}}` | nome completo da pessoa |
| `{{cpf}}` | CPF (só os dígitos) |
| `{{tipo_atividade}}` | tipo da atividade (ex.: Oficina) |
| `{{atividade}}` | título da atividade (vazio no certificado do evento) |
| `{{evento}}` | título do evento |
| `{{carga_horaria}}` | ex.: `8h` |
| `{{data}}` | data de emissão (`dd/mm/aaaa`) |
| `{{local}}` | local da atividade ou do evento |
| `{{qr}}` | imagem do QR de verificação (só no modo `.docx`) |
| `{{assinatura1}}` / `{{assinatura2}}` | imagem da assinatura (só no modo `.docx`) |
| `{{assinante1}}` / `{{cargo_assinante1}}` | nome/cargo do assinante (e 2) |

No modo **só texto** e **imagem de fundo**, use as variáveis de texto (o QR e as
assinaturas são desenhados automaticamente). No modo **`.docx`**, todas funcionam,
inclusive as imagens.

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
