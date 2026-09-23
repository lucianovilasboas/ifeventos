# Certificados — guia do organizador

Área por evento, aberta pelo botão **Certificado** na tela de atividades
(`/organizador/certificado/<evento_id>/config/`). Quem gerencia o evento
(dono, co-organizador ou staff) configura; o **catálogo de assinantes** fica em
`/organizador/assinantes/` (organizador e staff).

## O que se configura

- **Texto**: título, corpo e rodapé. O corpo aceita variáveis entre `{{ }}`.
- **Layout** (uma das duas formas):
  - **Fundo**: envie uma imagem (PNG/JPG) — ou PDF — como pano de fundo; o
    sistema desenha título, texto, assinaturas e QR por cima.
  - **Modelo `.docx`**: envie um documento do Word com as tags abaixo. O layout
    é totalmente livre (fontes, imagens, posições). Requer LibreOffice no
    servidor (já previsto no `Dockerfile`).
- **Assinaturas (1 ou 2)**: escolha do catálogo (nome, cargo e imagem da
  assinatura). A ordem na tela é a ordem no certificado.
- **Carga horária**: por atividade; se vazia, vale a do evento (ou a padrão da
  configuração).
- **Percentual mínimo de presença** (evento): quanto o aluno precisa comparecer,
  entre as atividades que **emitem certificado**, para ganhar o certificado do
  evento. Padrão 75%.
- **Enviar por e-mail**: manda o PDF em anexo ao participante.

## Variáveis do texto/template

| variável | valor |
| --- | --- |
| `{{nome}}` | nome completo da pessoa |
| `{{cpf}}` | CPF (só os dígitos) |
| `{{atividade}}` | título da atividade (vazio no certificado do evento) |
| `{{evento}}` | título do evento |
| `{{carga_horaria}}` | ex.: `8h` |
| `{{data}}` | data de emissão (`dd/mm/aaaa`) |
| `{{local}}` | local da atividade ou do evento |
| `{{qr}}` | imagem do QR de verificação (só no modo `.docx`) |
| `{{assinatura1}}` / `{{assinatura2}}` | imagem da assinatura (só no modo `.docx`) |
| `{{assinante1}}` / `{{cargo_assinante1}}` | nome/cargo do assinante (e 2) |

No modo **fundo**, use as variáveis de texto (imagens de assinatura/QR são
desenhadas automaticamente). No modo **`.docx`**, todas funcionam — inclusive as
imagens.

## Elegibilidade

- **Atividade**: a atividade precisa ter **"emite certificado"** marcado e a
  pessoa precisa ter **presença** (ou inscrição confirmada).
- **Evento**: presença mínima configurada, contando só as atividades que emitem
  certificado.

## Emissão

- Por inscrição, por atividade (todos os elegíveis) ou por evento (todos com o
  percentual mínimo) — nas telas atuais de certificados.
- Idempotente: não gera de novo o que já existe.
- Verificação pública pelo QR: `/c/<token>/`.
