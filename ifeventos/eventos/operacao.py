"""Briefing operacional do evento (execução, no dia).

Reúne o que o organizador precisa enxergar durante o evento: o que está
acontecendo agora, o que vem a seguir, presença/check-in e alertas. É tudo
derivado do banco (sem inventar). A "leitura do dia" pode ser narrada pela IA
com fallback determinístico.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from asgiref.sync import sync_to_async

from . import services
from .agenda import choques

logger = logging.getLogger("eventos.ia")

MODELO = settings.IA_MODELO_CLASSIFICACAO


def _atividades(evento):
    return list(
        evento.atividades.select_related("tipo").prefetch_related("palestrantes")
        .order_by("data_hora_inicio")
    )


def _ficha(atividade):
    presentes = atividade.presencas.count()
    inscritos = atividade.n_inscricoes or 0
    return {
        "atividade": atividade,
        "presentes": presentes,
        "inscritos": inscritos,
        "taxa": round(100 * presentes / inscritos) if inscritos else 0,
        "sem_checkin": max(inscritos - presentes, 0),
    }


def em_curso(evento, momento=None):
    momento = momento or timezone.now()
    return [
        _ficha(a) for a in _atividades(evento)
        if a.data_hora_inicio <= momento <= a.data_hora_fim
    ]


def a_seguir(evento, momento=None, horas=6):
    momento = momento or timezone.now()
    limite = momento + timedelta(hours=horas)
    return [
        _ficha(a) for a in _atividades(evento)
        if momento < a.data_hora_inicio <= limite
    ]


def alertas(evento, momento=None):
    """Avisos objetivos para a operação (texto)."""
    momento = momento or timezone.now()
    atividades = _atividades(evento)
    avisos = []

    for ficha in em_curso(evento, momento):
        if ficha["inscritos"] and ficha["presentes"] == 0:
            avisos.append("'%s' está em andamento e ainda não tem check-in." % ficha["atividade"].titulo)

    for ficha in a_seguir(evento, momento, horas=2):
        if ficha["inscritos"] == 0:
            avisos.append("'%s' começa em breve e não tem inscritos." % ficha["atividade"].titulo)

    conflitos = choques(atividades)
    if conflitos:
        avisos.append("%s conflito(s) de sala/palestrante na grade." % len(conflitos))

    rascunhos = sum(1 for a in atividades if not a.publicada)
    if rascunhos:
        avisos.append("%s atividade(s) seguem como rascunho (não aparecem na programação)." % rascunhos)

    return avisos


def resumo(evento, momento=None):
    momento = momento or timezone.now()
    hoje = timezone.localdate(momento)
    atividades = _atividades(evento)
    do_dia = [a for a in atividades if timezone.localtime(a.data_hora_inicio).date() == hoje]

    return {
        "momento": momento,
        "total_atividades": len(atividades),
        "atividades_hoje": len(do_dia),
        "em_curso": em_curso(evento, momento),
        "a_seguir": a_seguir(evento, momento),
        "alertas": alertas(evento, momento),
    }


# ---------------------------------------------------------------------------
# Leitura do dia (IA, com fallback)
# ---------------------------------------------------------------------------

def _contexto_texto(dados):
    linhas = [
        "Evento em andamento.",
        "Atividades em curso: %s." % (
            ", ".join("%s (%s/%s presentes)" % (
                f["atividade"].titulo, f["presentes"], f["inscritos"]
            ) for f in dados["em_curso"]) or "nenhuma"
        ),
        "A seguir (6h): %s." % (
            ", ".join(f["atividade"].titulo for f in dados["a_seguir"]) or "nenhuma"
        ),
        "Alertas: %s." % ("; ".join(dados["alertas"]) or "nenhum"),
    ]
    return "\n".join(linhas)


def leitura_basica(dados):
    if dados["em_curso"]:
        resumo = "Agora: %s." % ", ".join(
            "%s (%s/%s presentes)" % (f["atividade"].titulo, f["presentes"], f["inscritos"])
            for f in dados["em_curso"]
        )
    else:
        resumo = "Nenhuma atividade em curso neste momento."
    return {"leitura": resumo, "alertas": dados["alertas"], "origem": "heuristica", "aviso": ""}


async def leitura_do_dia(evento, momento=None):
    dados = await sync_to_async(resumo)(evento, momento)
    try:
        client = services.get_openai_client()
        resposta = await client.chat.completions.create(
            model=MODELO,
            messages=[{"role": "system", "content":
                "Você é o copiloto operacional de um evento de um campus do IFMG. "
                "Escreva UMA frase objetiva sobre o estado atual do evento, em português, "
                "sem inventar dados. Se houver alertas, cite o mais importante.\n\n"
                + _contexto_texto(dados)}],
            max_tokens=120,
            temperature=0.2,
        )
        services.registrar_uso_ia("briefing_operacional", MODELO, resposta)
        leitura = " ".join((resposta.choices[0].message.content or "").split())[:400]
        if leitura:
            return {"leitura": leitura, "alertas": dados["alertas"], "origem": "ia", "aviso": ""}
        return leitura_basica(dados)
    except Exception as erro:  # noqa: BLE001 - IA é acessória
        resultado = leitura_basica(dados)
        resultado["aviso"] = "A IA não está disponível agora (%s)." % erro
        return resultado
