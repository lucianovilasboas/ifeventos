"""Comunicação assistida do evento (rascunhos de divulgação).

Gera **rascunhos** de post (redes/WhatsApp) e de e-mail a partir dos dados do
evento. Nada é enviado automaticamente: o organizador copia/edita. Sem IA, um
modelo simples é montado com os dados do evento.
"""

import json
import logging

from . import services

logger = logging.getLogger("eventos.ia")

CANAIS = {"post": "Post para redes/WhatsApp", "email": "E-mail"}


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
