"""Concierge do participante (chat com a programação real).

Responde dúvidas do participante ("o que tem hoje?", "quantos dias faltam para
o evento?", "onde é a oficina de robótica?", "como tiro meu certificado?")
ancorado na **programação publicada** — o contexto é montado a partir do banco,
sem inventar atividades. O histórico da conversa é enviado pelo navegador (não
há persistência aqui); sem IA, devolve uma lista objetiva das próximas
atividades.

O contexto traz a **programação completa** dos eventos em andamento/futuros
(título, tipo, descrição, palestrantes por nome, local, horários absolutos,
vagas e período do evento) **mais a data/hora atuais** — é isso que permite ao
modelo responder perguntas com datas ("o que tem hoje", "faltam N dias", "o
evento acontece quando?") sem chutar. Não sai PII: nada de e-mail/CPF/telefone
nem lista de inscritos.
"""

import json
import logging

from django.utils import timezone
from asgiref.sync import sync_to_async

from . import services
from . import contexto_ia
from .models import Atividade, Evento, sem_acento

logger = logging.getLogger("eventos.ia")

MAX_MENSAGEM = 600
MAX_ITENS = 60
MAX_HISTORICO = 6
MAX_CATALOGO = 300
DESC_LIMITE = 240

# Perguntas frequentes usadas no autocomplete (e como exemplos no chat).
FAQ = [
    "O que tem hoje?",
    "O que tem na quinta à tarde?",
    "Quantos dias faltam para o evento?",
    "Quais eventos acontecem hoje?",
    "Quais atividades ainda têm vagas?",
    "Onde é a oficina de robótica?",
    "Como faço minha inscrição?",
    "Como tiro meu certificado?",
    "Onde fica o auditório?",
]


# ---------------------------------------------------------------------------
# Datas: o modelo precisa da data de hoje e de datas absolutas/relativas.
# ---------------------------------------------------------------------------

_DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _data_localizada(valor):
    """Data/hora no fuso do site, formatada para o modelo (dd/mm/aaaa hh:mm)."""
    if not valor:
        return ""
    return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M")


def _data_evento(valor):
    """Data de um evento (campo DateField) em dd/mm/aaaa."""
    if not valor:
        return ""
    return valor.strftime("%d/%m/%Y")


def _agora_legivel(agora=None):
    """Linha "Agora" em português: sábado, 20/09/2026, 14h30."""
    agora = agora or timezone.now()
    local = timezone.localtime(agora)
    dia = _DIAS_SEMANA[local.weekday()]
    return "%s, %s, %sh%02d" % (dia, local.strftime("%d/%m/%Y"), local.hour, local.minute)


def _rotulo_relativo(inicio, fim, agora=None):
    """Etiqueta de tempo relativa de uma atividade: hoje, amanhã, em N dias…"""
    agora = agora or timezone.now()
    local = timezone.localtime(agora)
    hoje = local.date()
    ini = timezone.localtime(inicio).date() if inicio else None
    fim_dia = timezone.localtime(fim).date() if fim else None

    if ini and fim and ini <= hoje <= fim_dia:
        if timezone.localtime(inicio) <= agora <= timezone.localtime(fim):
            return "acontecendo agora"
        if ini == hoje:
            return "hoje"
        delta = (ini - hoje).days
        if delta == 1:
            return "amanhã"
        return "em %s dias" % delta
    if ini and fim and hoje < ini:
        delta = (ini - hoje).days
        if delta == 1:
            return "começa amanhã"
        return "começa em %s dias" % delta
    if fim_dia and fim_dia == hoje:
        return "encerra hoje"
    return ""


# ---------------------------------------------------------------------------
# Contexto: eventos ativos + programação completa
# ---------------------------------------------------------------------------

def catalogo(agora=None, limite=MAX_ITENS):
    """Atividades publicadas ainda não encerradas (usado nas sugestões)."""
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


def eventos_ativos(agora=None, limite=20):
    """Eventos em andamento ou futuros, com período e nº de atividades públicas."""
    from django.db.models import Count, Q

    agora = agora or timezone.now()
    hoje = timezone.localdate()
    eventos = (
        Evento.objects.filter(data_fim__gte=hoje)
        .annotate(n_atividades=Count("atividades", filter=Q(atividades__publicada=True)))
        .order_by("data_inicio", "id")[:limite]
    )
    return [
        {
            "titulo": evento.title,
            "categoria": evento.get_categoria_display(),
            "inicio": _data_evento(evento.data_inicio),
            "fim": _data_evento(evento.data_fim),
            "local": evento.local or "",
            "n_atividades": evento.n_atividades,
        }
        for evento in eventos
    ]


def catalogo_completo(agora=None, limite=MAX_CATALOGO):
    """Programação completa (publicada) dos eventos ativos, inclusive dias já
    passados dentro do período — é o que permite responder sobre "o evento todo".
    """
    agora = agora or timezone.now()
    hoje = timezone.localdate()
    atividades = (
        Atividade.objects.filter(publicada=True, evento__data_fim__gte=hoje)
        .select_related("evento", "tipo")
        .prefetch_related("palestrantes")
        .order_by("data_hora_inicio", "id")[:limite]
    )
    itens = []
    for atividade in atividades:
        palestrantes = [
            (p.get_full_name() or p.first_name or "").strip()
            for p in atividade.palestrantes.all()
        ]
        itens.append({
            "titulo": atividade.titulo,
            "descricao": " ".join((atividade.descricao or "").split())[:DESC_LIMITE],
            "tipo": atividade.tipo.nome if atividade.tipo_id else "",
            "evento": atividade.evento.title,
            "evento_inicio": _data_evento(atividade.evento.data_inicio),
            "evento_fim": _data_evento(atividade.evento.data_fim),
            "local": atividade.local or atividade.evento.local or "",
            "inicio": _data_localizada(atividade.data_hora_inicio),
            "fim": _data_localizada(atividade.data_hora_fim),
            "quando": atividade.quando_legivel,
            "relativo": _rotulo_relativo(atividade.data_hora_inicio, atividade.data_hora_fim, agora),
            "vagas": atividade.vagas_disponiveis(),
            "vagas_totais": atividade.n_vagas or 0,
            "emite_certificado": atividade.emite_certificado,
            "palestrantes": palestrantes,
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


def contexto_completo_texto(itens):
    """Versão textual da programação completa, com datas absolutas + relativas."""
    if not itens:
        return "(não há atividades publicadas)"
    linhas = []
    for i in itens:
        palestrantes = ", ".join(i["palestrantes"]) or "—"
        certificado = "emite certificado" if i["emite_certificado"] else "sem certificado"
        linhas.append(
            "- %s | tipo: %s | evento: %s (%s a %s) | quando: %s (%s) | "
            "local: %s | vagas: %s/%s | %s | palestrantes: %s | descrição: %s"
            % (i["titulo"], i["tipo"] or "—", i["evento"], i["evento_inicio"],
               i["evento_fim"], i["quando"], i["relativo"], i["local"] or "—",
               i["vagas"], i["vagas_totais"], certificado, palestrantes,
               i["descricao"] or "—")
        )
    return "\n".join(linhas)


def eventos_texto(eventos):
    if not eventos:
        return "(nenhum evento em andamento ou futuro)"
    return "\n".join(
        "- %s | categoria: %s | %s a %s | local: %s | %s atividade(s)"
        % (e["titulo"], e["categoria"], e["inicio"], e["fim"],
           e["local"] or "—", e["n_atividades"])
        for e in eventos
    )


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _prompt(agora_linha, eventos_txt, programacao_txt, campus=""):
    return """Você é o assistente do portal de eventos do IFMG Campus Ponte Nova.

Hoje é {agora}. Use essa data como referência para responder perguntas sobre
datas: "hoje", "amanhã", "quantos dias faltam", quando um evento começa ou
termina. Faça a conta com as datas fornecidas; não adivinhe nem invente.

=== CONTEXTO DO CAMPUS (catálogos) ===
{campus}
=== FIM DO CONTEXTO ===

=== EVENTOS (em andamento ou futuros) ===
{eventos}
=== FIM DOS EVENTOS ===

=== PROGRAMAÇÃO (atividades publicadas) ===
{programacao}
=== FIM DA PROGRAMAÇÃO ===

Responda à pergunta do participante usando SOMENTE as informações acima.
Regras:
- "o que tem hoje" = somente atividades marcadas como "(hoje)" ou
  "(acontecendo agora)".
- Se não houver atividade hoje, diga isso e cite a próxima.
- "quantos dias faltam para o evento" = calcule da data de hoje até o início
  do evento/atividade.
- Se a resposta não estiver nas informações, diga que não encontrou e sugira
  ver a agenda (/eventos/).
- Não invente atividades, horários, locais ou pessoas; não peça nem informe
  dados pessoais.
- Seja curto (no máximo 5 linhas) e cordial.""".format(
        agora=agora_linha,
        campus=campus or "(sem catálogo)",
        eventos=eventos_txt,
        programacao=programacao_txt,
    )


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


def sugestoes(consulta, limite=8):
    """Sugestões para o autocomplete do chat (atividades, eventos e FAQ)."""
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

    agora = timezone.now()
    itens = await sync_to_async(catalogo_completo)(agora)
    eventos = await sync_to_async(eventos_ativos)(agora)
    campus = contexto_ia.resumo_texto(await sync_to_async(contexto_ia.dossie)())
    agora_linha = _agora_legivel(agora)
    eventos_txt = eventos_texto(eventos)
    programacao_txt = contexto_completo_texto(itens)
    try:
        messages = [{
            "role": "system",
            "content": _prompt(agora_linha, eventos_txt, programacao_txt, campus),
        }]
        messages += _normaliza_historico(historico)
        messages.append({"role": "user", "content": mensagem})
        resposta = await services.gerar_chat(
            "concierge", messages=messages, max_tokens=500, temperature=0.2
        )
        texto = (resposta.choices[0].message.content or "").strip()
        if texto:
            return {"resposta": texto, "origem": "ia", "aviso": ""}
        return resposta_basica(itens, mensagem)
    except Exception as erro:  # noqa: BLE001 - IA é acessória
        resultado = resposta_basica(itens, mensagem)
        resultado["aviso"] = "A IA não está disponível agora (%s)." % erro
        return resultado