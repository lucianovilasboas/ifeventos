"""Concierge do participante (chat com a programação real).

Responde dúvidas do participante ("o que tem quinta à tarde?", "onde é a
oficina de robótica?", "como tiro meu certificado?") ancorado na **programação
publicada** — o contexto é montado a partir do banco, sem inventar atividades.
O histórico da conversa é enviado pelo navegador (não há persistência aqui);
sem IA, devolve uma lista objetiva das próximas atividades.

Porta o padrão do `mychatbot` (conversa com histórico) para dentro do
IFEventos, adaptado ao participante e às regras de privacidade.
"""

import json
import logging

from django.conf import settings
from django.utils import timezone
from asgiref.sync import sync_to_async

from . import services
from .models import Atividade, Evento, sem_acento

logger = logging.getLogger("eventos.ia")

MODELO = settings.IA_MODELO_CLASSIFICACAO

MAX_MENSAGEM = 600
MAX_ITENS = 60
MAX_HISTORICO = 6

# Perguntas frequentes usadas no autocomplete (e como exemplos no chat).
FAQ = [
    "O que tem hoje?",
    "O que tem na quinta à tarde?",
    "Quais atividades ainda têm vagas?",
    "Onde é a oficina de robótica?",
    "Como faço minha inscrição?",
    "Como tiro meu certificado?",
    "Onde fica o auditório?",
]


def catalogo(agora=None, limite=MAX_ITENS):
    """Atividades publicadas ainda não encerradas, para ancorar as respostas."""
    agora = agora or timezone.now()
    atividades = (
        Atividade.objects.filter(publicada=True, data_hora_fim__gte=agora)
        .select_related("evento", "tipo")
        .order_by("data_hora_inicio")[:limite]
    )
    itens = []
    for atividade in atividades:
        itens.append({
            "titulo": atividade.titulo,
            "tipo": atividade.tipo.nome if atividade.tipo_id else "",
            "evento": atividade.evento.title,
            "local": atividade.local or atividade.evento.local or "",
            "quando": atividade.quando_legivel,
            "vagas": atividade.vagas_disponiveis(),
        })
    return itens


def contexto_texto(itens):
    if not itens:
        return "(não há atividades publicadas a partir de agora)"
    return "\n".join(
        "- %s | tipo: %s | evento: %s | quando: %s | local: %s | vagas: %s"
        % (i["titulo"], i["tipo"] or "—", i["evento"], i["quando"],
           i["local"] or "—", i["vagas"])
        for i in itens
    )


def sugestoes(consulta, limite=8):
    """Sugestões para o autocomplete do chat (atividades, eventos e FAQ).

    Com menos de 2 caracteres devolve as perguntas frequentes e alguns títulos
    próximos. A busca no banco usa `icontains`; as duplicatas são removidas sem
    diferenciar acento/caixa.
    """
    consulta = " ".join((consulta or "").split())
    itens, vistos = [], set()

    def adicionar(texto):
        texto = " ".join(str(texto or "").split())
        chave = sem_acento(texto)
        if texto and chave not in vistos:
            vistos.add(chave)
            itens.append(texto)

    if len(consulta) < 2:
        for pergunta in FAQ:
            adicionar(pergunta)
        for atividade in catalogo(limite=4):
            adicionar(atividade["titulo"])
        return itens[:limite]

    termo = sem_acento(consulta)
    for pergunta in FAQ:
        if termo in sem_acento(pergunta):
            adicionar(pergunta)

    agora = timezone.now()
    titulos = (
        Atividade.objects.filter(
            publicada=True, data_hora_fim__gte=agora, titulo__icontains=consulta
        )
        .order_by("data_hora_inicio")
        .values_list("titulo", flat=True)[:6]
    )
    for titulo in titulos:
        adicionar(titulo)
    for titulo in Evento.objects.filter(title__icontains=consulta).values_list(
        "title", flat=True
    )[:4]:
        adicionar(titulo)
    return itens[:limite]


def _prompt(itens):
    return """Você é o assistente do portal de eventos do IFMG Campus Ponte Nova.

Responda à pergunta do participante usando SOMENTE as atividades publicadas
listadas abaixo. Se a resposta não estiver na lista, diga que não encontrou na
programação e sugira ver a agenda. Não invente atividades, horários ou locais.
Não peça nem informe dados pessoais. Seja curto (no máximo 4 linhas) e cordial.
Quando citar uma página do portal, inclua o endereço (ex.: a agenda é /eventos/;
certificados, /participante/meus-certificados/).

Programação publicada:
{programacao}""".format(programacao=contexto_texto(itens))


def resposta_basica(itens, mensagem=""):
    if not itens:
        return {
            "resposta": "Não encontrei atividades publicadas no momento. Veja a agenda em /eventos/.",
            "origem": "heuristica", "aviso": "",
        }
    linhas = [
        "%s — %s (%s)" % (i["titulo"], i["quando"], i["local"] or "local a confirmar")
        for i in itens[:5]
    ]
    return {
        "resposta": "Estas são as próximas atividades:\n" + "\n".join(linhas) +
                    "\n\nA programação completa está em /eventos/.",
        "origem": "heuristica", "aviso": "",
    }


def _normaliza_historico(historico):
    mensagens = []
    for item in (historico or [])[-MAX_HISTORICO:]:
        if not isinstance(item, dict):
            continue
        texto = str(item.get("texto") or "").strip()[:MAX_MENSAGEM]
        if not texto:
            continue
        papel = "assistant" if item.get("papel") == "assistant" else "user"
        mensagens.append({"role": papel, "content": texto})
    return mensagens


async def responder(mensagem, historico=None):
    """Responde à pergunta do participante. Sem IA, lista as próximas atividades."""
    mensagem = (mensagem or "").strip()[:MAX_MENSAGEM]
    if not mensagem:
        return {"erro": "Escreva uma pergunta.", "origem": None}

    itens = await sync_to_async(catalogo)()
    try:
        client = services.get_openai_client()
        messages = [{"role": "system", "content": _prompt(itens)}]
        messages += _normaliza_historico(historico)
        messages.append({"role": "user", "content": mensagem})
        resposta = await client.chat.completions.create(
            model=MODELO,
            messages=messages,
            max_tokens=500,
            temperature=0.2,
        )
        services.registrar_uso_ia("concierge", MODELO, resposta)
        texto = (resposta.choices[0].message.content or "").strip()
        if texto:
            return {"resposta": texto, "origem": "ia", "aviso": ""}
        return resposta_basica(itens, mensagem)
    except Exception as erro:  # noqa: BLE001 - IA é acessória
        resultado = resposta_basica(itens, mensagem)
        resultado["aviso"] = "A IA não está disponível agora (%s)." % erro
        return resultado
