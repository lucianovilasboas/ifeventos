"""Comunicação assistida do evento (rascunhos de divulgação).

Gera **rascunhos** de post (redes/WhatsApp) e de e-mail a partir dos dados do
evento. Nada é enviado automaticamente: o organizador copia/edita. Sem IA, um
modelo simples é montado com os dados do evento.
"""

import json
import logging
import re

from . import services
from .tempo import local_legivel

logger = logging.getLogger("eventos.ia")

CANAIS = {"post": "Post para redes/WhatsApp", "email": "E-mail"}

# Modelos de mensagem oferecidos na tela de comunicação do organizador.
MODELOS_EMAIL = {
    "livre": "Mensagem livre",
    "lembrete_evento": "Lembrete do evento",
    "lembrete_atividade": "Lembrete de atividade",
    "convite": "Convite",
    "agradecimento": "Agradecimento",
}


def _periodo(evento):
    if evento.data_inicio == evento.data_fim:
        return evento.data_inicio.strftime("%d/%m/%Y")
    return "%s a %s" % (evento.data_inicio.strftime("%d/%m/%Y"),
                        evento.data_fim.strftime("%d/%m/%Y"))


def rascunho_basico(evento, canal, objetivo=""):
    """Rascunho determinístico, montado com os dados do evento."""
    periodo = _periodo(evento)
    local = evento.local or "IFMG Campus Ponte Nova"
    descricao = (evento.description or "").strip()

    if canal == "email":
        assunto = "Convite: %s" % evento.title
        corpo = (
            "Olá, 📩\n\n"
            "É com prazer que convidamos você para o evento %s.\n\n"
            "%s\n\n"
            "Data: %s 📅\nLocal: %s\n\n"
            "%s\n\n"
            "Contamos com a sua participação. 🎉\n"
            "Organização"
        ) % (evento.title, descricao, periodo, local,
             (objetivo or "Confira a programação completa e inscreva-se.").strip())
    else:
        assunto = ""
        corpo = (
            "📢 %s\n\n%s\n\nData: %s 📅\nLocal: %s\n\n%s 🎟️"
        ) % (evento.title, descricao, periodo, local,
             (objetivo or "Participe! Inscrições abertas.").strip())
    return {"canal": canal, "assunto": assunto, "corpo": corpo,
            "origem": "heuristica", "aviso": ""}


def _prompt(evento, canal, objetivo):
    return """Você escreve a divulgação de eventos de um campus do IFMG.

Evento: {titulo}
Tema: {categoria}
Descrição: {descricao}
Data: {periodo}
Local: {local}
Canal: {canal}
Objetivo/pedido do organizador: {objetivo}

Escreva um rascunho em português. Regras:
1. Se for "post", escreva um texto curto (até 6 linhas) para redes sociais/WhatsApp.
2. Se for "email", escreva um e-mail com "assunto" e "corpo" (saudação e despedida).
3. Use 1 a 2 emojis por parágrafo, coerentes com o conteúdo (não poluir o texto).
4. Não invente informações que não estão acima.

Responda SOMENTE com JSON: {{"assunto": "<ou vazio>", "corpo": "<texto>"}}""".format(
        titulo=evento.title,
        categoria=evento.get_categoria_display(),
        descricao=(evento.description or "").strip() or "(sem descrição)",
        periodo=_periodo(evento),
        local=evento.local or "IF Campus Ponte Nova",
        canal="post" if canal == "post" else "email",
        objetivo=objetivo or "(nenhum)",
    )


async def gerar_rascunho(evento, canal="post", objetivo=""):
    """Gera um rascunho de divulgação (IA) com fallback determinístico."""
    canal = canal if canal in CANAIS else "post"
    try:
        resposta = await services.gerar_chat(
            "comunicacao",
            messages=[{"role": "system", "content": _prompt(evento, canal, objetivo)}],
            response_format={"type": "json_object"},
            max_tokens=700,
            temperature=0.5,
        )
        dados = json.loads(resposta.choices[0].message.content or "{}")
        corpo = str(dados.get("corpo") or "").strip()[:2500]
        assunto = " ".join(str(dados.get("assunto") or "").split())[:160]
        if not corpo:
            return rascunho_basico(evento, canal, objetivo)
        return {"canal": canal, "assunto": assunto, "corpo": corpo,
                "origem": "ia", "aviso": ""}
    except Exception as erro:  # noqa: BLE001 - IA é acessória
        resultado = rascunho_basico(evento, canal, objetivo)
        resultado["aviso"] = "A IA não está disponível agora; usei o modelo padrão (%s)." % erro
        return resultado


# ---------------------------------------------------------------------------
# E-mail para o público do evento (tela de comunicação do organizador)
# ---------------------------------------------------------------------------
def _quando_atividade(atividade):
    """Data/hora da atividade em texto curto: `10/10/2026 às 19:30`."""
    if atividade is None or not atividade.data_hora_inicio:
        return ""
    texto = local_legivel(atividade.data_hora_inicio, "%d/%m/%Y às %H:%M")
    if atividade.data_hora_fim:
        texto += " até " + local_legivel(atividade.data_hora_fim, "%H:%M")
    return texto


def _local_atividade(evento, atividade):
    if atividade is not None and (atividade.local or "").strip():
        return atividade.local.strip()
    return (evento.local or "").strip()


def email_basico(evento, modelo="livre", atividade=None, publico="", objetivo=""):
    """E-mail determinístico, montado com os dados do evento/atividade.

    Serve de fallback quando a IA está desligada ou indisponível: a tela nunca
    fica sem assunto e corpo.
    """
    modelo = modelo if modelo in MODELOS_EMAIL else "livre"
    periodo = _periodo(evento)
    local = (evento.local or "").strip() or "IFMG Campus Ponte Nova"
    pedido = (objetivo or "").strip()
    quando = _quando_atividade(atividade)
    local_atividade = _local_atividade(evento, atividade)
    descricao = (evento.description or "").strip()

    if modelo == "lembrete_evento":
        assunto = "Lembrete: %s (%s)" % (evento.title, periodo)
        corpo = (
            "Olá,\n\n"
            "Passando para lembrar do evento %s, que acontece em %s, em %s.\n\n"
            "%s\n\n"
            "Contamos com a sua participação.\n\n"
            "Organização do evento %s"
        ) % (
            evento.title, periodo, local,
            pedido or "Confira a programação completa e organize-se para chegar no horário.",
            evento.title,
        )
    elif modelo == "lembrete_atividade":
        titulo = atividade.titulo if atividade else evento.title
        assunto = "Lembrete: %s" % titulo
        corpo = (
            "Olá,\n\n"
            "Lembrete: a atividade \"%s\" acontece em %s, em %s.\n\n"
            "%s\n\n"
            "Organização do evento %s"
        ) % (
            titulo, quando or periodo, local_atividade,
            pedido or "Chegue com alguns minutos de antecedência.",
            evento.title,
        )
    elif modelo == "convite":
        assunto = "Convite: %s" % evento.title
        corpo = (
            "Olá,\n\n"
            "É com prazer que convidamos você para o evento %s.\n\n"
            "%s\n\n"
            "Data: %s\nLocal: %s\n\n"
            "%s\n\n"
            "Organização do evento %s"
        ) % (
            evento.title, descricao or "Confira a programação completa.",
            periodo, local,
            pedido or "Sua participação é muito bem-vinda.",
            evento.title,
        )
    elif modelo == "agradecimento":
        assunto = "Obrigado por participar — %s" % evento.title
        corpo = (
            "Olá,\n\n"
            "Obrigado por participar do evento %s. Sua presença fez a diferença!\n\n"
            "%s\n\n"
            "Organização do evento %s"
        ) % (
            evento.title,
            pedido or "Em breve você poderá acessar os certificados pelo site.",
            evento.title,
        )
    else:
        assunto = "Comunicado — %s" % evento.title
        corpo = (
            "Olá,\n\n"
            "%s\n\n"
            "Evento: %s\nData: %s\nLocal: %s\n\n"
            "Organização do evento %s"
        ) % (
            pedido or "Segue uma mensagem da organização do evento.",
            evento.title, periodo, local, evento.title,
        )

    return {"assunto": assunto[:160], "corpo": corpo.strip()[:5000],
            "origem": "heuristica", "aviso": ""}


def _sem_markdown(texto):
    """Remove marcações de Markdown que o modelo às vezes adiciona.

    O e-mail é texto puro: `**negrito**` apareceria com asteriscos na caixa de
    entrada. Remove negrito/itálico, títulos e marcadores de lista.
    """
    texto = str(texto or "")
    texto = re.sub(r"\*\*(.+?)\*\*", r"\1", texto, flags=re.S)
    texto = re.sub(r"__(.+?)__", r"\1", texto, flags=re.S)
    texto = re.sub(r"(?m)^#{1,6}\s+", "", texto)
    texto = re.sub(r"(?m)^\s*[-*]\s+", "", texto)
    return texto


def _prompt_email(evento, modelo, atividade, publico, objetivo):
    atividade_texto = "(nenhuma)"
    if atividade is not None:
        atividade_texto = "%s — %s — %s" % (
            atividade.titulo, _quando_atividade(atividade), _local_atividade(evento, atividade)
        )
    return """Você escreve e-mails de um organizador de eventos de um campus do IFMG.

Evento: {titulo}
Tema: {categoria}
Descrição: {descricao}
Data: {periodo}
Local: {local}
Público escolhido: {publico}
Modelo: {modelo}
Atividade de referência: {atividade}
Pedido do organizador: {objetivo}

Escreva um e-mail em português. Regras:
1. Assunto curto (até 80 caracteres), sem "RE:" nem clichês.
2. Corpo com saudação e despedida, direto e cordial; 0 a 2 emojis no total.
3. Se for lembrete, destaque data, horário e local.
4. Se for agradecimento, não peça nada de volta.
5. Não invente dados que não estão acima.
6. Texto puro: NÃO use Markdown (sem **negrito**, __itálico__, ## títulos,
   listas com - ou *).

Responda SOMENTE com JSON: {{"assunto": "<texto>", "corpo": "<texto>"}}""".format(
        titulo=evento.title,
        categoria=evento.get_categoria_display(),
        descricao=(evento.description or "").strip() or "(sem descrição)",
        periodo=_periodo(evento),
        local=(evento.local or "").strip() or "IFMG Campus Ponte Nova",
        publico=(publico or "").strip() or "pessoas do evento",
        modelo=MODELOS_EMAIL.get(modelo, MODELOS_EMAIL["livre"]),
        atividade=atividade_texto,
        objetivo=(objetivo or "").strip() or "(nenhum pedido específico)",
    )


async def gerar_email(evento, modelo="livre", atividade=None, publico="", objetivo=""):
    """Gera assunto e corpo por IA, com fallback determinístico.

    `publico` é só contexto para o texto (ex.: "Palestrantes, Participantes");
    não muda quem recebe — os destinatários são resolvidos no envio.
    """
    modelo = modelo if modelo in MODELOS_EMAIL else "livre"
    try:
        resposta = await services.gerar_chat(
            "comunicacao",
            messages=[{
                "role": "system",
                "content": _prompt_email(evento, modelo, atividade, publico, objetivo),
            }],
            response_format={"type": "json_object"},
            max_tokens=800,
            temperature=0.5,
        )
        dados = json.loads(resposta.choices[0].message.content or "{}")
        assunto = _sem_markdown(
            " ".join(str(dados.get("assunto") or "").split())
        )[:160]
        corpo = _sem_markdown(str(dados.get("corpo") or "")).strip()[:5000]
        if not assunto or not corpo:
            return email_basico(evento, modelo, atividade, publico, objetivo)
        return {"assunto": assunto, "corpo": corpo, "origem": "ia", "aviso": ""}
    except Exception as erro:  # noqa: BLE001 - IA é acessória
        resultado = email_basico(evento, modelo, atividade, publico, objetivo)
        resultado["aviso"] = "A IA não está disponível agora; usei o modelo padrão (%s)." % erro
        return resultado
