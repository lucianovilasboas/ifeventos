"""Diagnóstico da trilha de auditoria: causa provável + solução.

Complementa o agente de perguntas (`eventos/auditor_ia.py`) com um **relatório
de diagnóstico**: em vez de só contar, ele interpreta os erros da janela e
aponta causa e o que fazer.

Três camadas, de propósito:
  1. **Sinais** (determinístico, `coletar_sinais`): agrupa erros por logger +
     assinatura normalizada, mede tendência/picos, status HTTP e marcos. Os
     NÚMEROS são calculados no ORM — a IA não inventa.
  2. **Playbooks** (`eventos/auditoria_playbooks.py`): onde a assinatura é
     conhecida, a causa/solução sai pronta (revisável, versionada).
  3. **IA** (contexto `auditoria_diagnostico`): só interpreta os sinais + os
     playbooks casados e devolve um JSON estruturado, validado aqui.

Restrito ao superusuário (a rota garante) e sem expor PII: tracebacks passam por
máscara de e-mail/CPF antes de virarem sinal.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from . import auditoria, services
from .auditoria_playbooks import playbooks_para, topico_do_logger
from .models import RegistroAuditoria

logger = logging.getLogger("eventos.ia")

SEVERIDADES = ("critico", "alto", "medio", "baixo", "ok")

_RE_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_RE_HEX = re.compile(r"\b[0-9a-fA-F]{8,}\b")
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RE_CPF = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")


def normalizar_assinatura(texto):
    """Assinatura estável de um erro: troca números/ids por marcadores.

    Sem isso, cada ocorrência com um id diferente viraria um "grupo" próprio e o
    diagnóstico não enxergaria a recorrência (ex.: "atividade 42" e "atividade 43").
    """
    texto = _RE_UUID.sub("<uuid>", texto or "")
    texto = _RE_HEX.sub("<hex>", texto)
    texto = re.sub(r"\d+", "<n>", texto)
    return re.sub(r"\s+", " ", texto).strip()[:200]


def _mascarar_traceback(texto):
    """Máscara de e-mail/CPF — traceback pode carregar dado pessoal em SQL/params."""
    texto = _RE_EMAIL.sub(lambda m: auditoria.mascarar_email(m.group(0)), texto or "")
    texto = _RE_CPF.sub("<cpf>", texto)
    return texto[:2000]


def _janela(desde=None, ate=None, dias_padrao=7):
    ate = ate or timezone.now()
    desde = desde or (ate - timedelta(days=dias_padrao))
    return desde, ate


def coletar_sinais(usuario, desde, ate, limite_grupos=15):
    """Calcula os sinais (números) da trilha no período, com escopo do usuário."""
    base = auditoria.escopo_para_usuario(RegistroAuditoria.objects.all(), usuario)
    base = base.filter(criado_em__gte=desde, criado_em__lte=ate)

    # --- erros agrupados por (logger, assinatura) ---
    erros = base.filter(acao=RegistroAuditoria.ACAO_ERRO)
    grupos = {}
    for linha in erros.order_by("criado_em")[:1000]:
        detalhes = linha.detalhes or {}
        logger_nome = (detalhes.get("logger") or "")[:60]
        assinatura = normalizar_assinatura(linha.resumo)
        chave = (logger_nome, assinatura)
        grupo = grupos.get(chave)
        if grupo is None:
            grupo = grupos[chave] = {
                "logger": logger_nome,
                "assinatura": assinatura,
                "ocorrencias": 0,
                "primeira": None,
                "ultima": None,
                "exemplo": linha.resumo[:255],
                "traceback": "",
            }
        grupo["ocorrencias"] += 1
        quando = linha.criado_em.isoformat() if linha.criado_em else None
        grupo["primeira"] = grupo["primeira"] or quando
        grupo["ultima"] = quando
        if not grupo["traceback"] and detalhes.get("traceback"):
            grupo["traceback"] = _mascarar_traceback(detalhes["traceback"])

    # Casa playbooks por grupo e ordena pelos mais frequentes.
    lista_grupos = []
    for grupo in grupos.values():
        texto = grupo["exemplo"] + "\n" + grupo["traceback"]
        casados = playbooks_para(texto, grupo["logger"])
        grupo["playbooks"] = [
            {
                "id": pb["id"],
                "titulo": pb["titulo"],
                "severidade": pb["severidade"],
                "causa": pb["causa"],
                "solucao": pb["solucao"],
                "onde": pb["onde"],
            }
            for pb in casados
        ]
        grupo["logger_cobre"] = topico_do_logger(grupo["logger"])
        lista_grupos.append(grupo)
    lista_grupos.sort(key=lambda g: g["ocorrencias"], reverse=True)
    lista_grupos = lista_grupos[:limite_grupos]

    # --- tendência por dia + picos ---
    tendencia = [
        {"dia": item["dia"].isoformat(), "total": item["total"]}
        for item in base.annotate(dia=TruncDate("criado_em"))
        .values("dia")
        .annotate(total=Count("id"))
        .order_by("dia")
    ]
    totais = [t["total"] for t in tendencia]
    picos = []
    if len(totais) >= 3:
        media = sum(totais) / len(totais)
        desvio = (sum((x - media) ** 2 for x in totais) / len(totais)) ** 0.5
        limite = media + max(desvio, 1.0)
        picos = [t for t in tendencia if t["total"] > limite]

    # --- HTTP (status gravado pelo handler do django.request) ---
    http_status = [
        {"status": item["status"], "total": item["total"]}
        for item in base.filter(status__isnull=False)
        .values("status")
        .annotate(total=Count("id"))
        .order_by("-total")[:10]
    ]

    acoes_top = [
        {"acao": item["acao"], "total": item["total"]}
        for item in base.values("acao").annotate(total=Count("id")).order_by("-total")[:10]
    ]
    entidades_top = [
        {"entidade": item["entidade"], "total": item["total"]}
        for item in base.exclude(entidade="")
        .values("entidade")
        .annotate(total=Count("id"))
        .order_by("-total")[:10]
    ]

    def _contar_acao(acao):
        return base.filter(acao=acao).count()

    marcos = {
        "excluir": _contar_acao(RegistroAuditoria.ACAO_EXCLUIR),
        "cancelar_presenca": _contar_acao(RegistroAuditoria.ACAO_CANCELAR_PRESENCA),
        "importar": _contar_acao(RegistroAuditoria.ACAO_IMPORTAR),
        "login": _contar_acao(RegistroAuditoria.ACAO_LOGIN),
    }

    return {
        "periodo": {
            "desde": desde.isoformat(),
            "ate": ate.isoformat(),
            "dias": max(1, (ate - desde).days or 1),
        },
        "total_registros": base.count(),
        "erros_total": erros.count(),
        "erros_grupos": lista_grupos,
        "tendencia": tendencia,
        "picos": picos,
        "http_status": http_status,
        "acoes_top": acoes_top,
        "entidades_top": entidades_top,
        "marcos": marcos,
    }


def severidade_deterministica(sinais):
    """Piso de severidade calculado dos sinais (vale mesmo sem a IA)."""
    escala = {"critico": 4, "alto": 3, "medio": 2, "baixo": 1, "ok": 0}
    pior = 0
    for grupo in sinais.get("erros_grupos", []):
        for pb in grupo.get("playbooks", []):
            pior = max(pior, escala.get(pb.get("severidade"), 1))
    # Qualquer erro sem playbook já é, no mínimo, "medio" se for recorrente.
    if any(g["ocorrencias"] >= 3 for g in sinais.get("erros_grupos", [])):
        pior = max(pior, 2)
    # 5xx no HTTP é pelo menos "alto".
    if any(500 <= (h.get("status") or 0) < 600 for h in sinais.get("http_status", [])):
        pior = max(pior, 3)
    if pior == 0:
        return "ok"
    for nome in ("critico", "alto", "medio", "baixo"):
        if pior >= escala[nome]:
            return nome
    return "baixo"


def _prompt_diagnostico():
    return (
        "Você é o AuditorIA, que diagnostica a saúde do sistema a partir da trilha "
        "de auditoria. Recebe um JSON com SINAIS já calculados (erros agrupados, "
        "tendência, picos, status HTTP, marcos), os PLAYBOOKS conhecidos casados em "
        "cada grupo e um MAPA de loggers para módulos.\n"
        "Responda SOMENTE com JSON válido no formato:\n"
        '{"severidade_geral":"critico|alto|medio|baixo|ok","resumo":"1 a 3 frases",'
        '"itens":[{"titulo":"","severidade":"critico|alto|medio|baixo","evidencia":"",'
        '"causa_provavel":"","solucao":"","onde":""}]}\n'
        "Regras:\n"
        "- Baseie-se SOMENTE nos sinais; cite os NÚMEROS (não invente).\n"
        "- Para grupos com playbook, use a causa/solução do playbook.\n"
        "- Para grupos sem playbook, proponha a causa MAIS PROVÁVEL e passos "
        "concretos usando o mapa de loggers e o traceback.\n"
        "- Priorize: no máximo 8 itens, do mais grave/recorrente para o menos.\n"
        "- Sem erro relevante: severidade_geral 'ok' e itens vazio.\n"
        "- Nada de markdown; só o JSON."
    )


def _conteudo(resposta) -> str:
    try:
        return (resposta.choices[0].message.content or "").strip()
    except Exception:
        return ""


def _limpar_item(item):
    if not isinstance(item, dict):
        return None
    severidade = str(item.get("severidade") or "").strip().lower()
    if severidade not in SEVERIDADES:
        severidade = "medio"
    return {
        "titulo": str(item.get("titulo") or "").strip()[:160],
        "severidade": severidade,
        "evidencia": str(item.get("evidencia") or "").strip()[:400],
        "causa_provavel": str(item.get("causa_provavel") or "").strip()[:600],
        "solucao": str(item.get("solucao") or "").strip()[:800],
        "onde": str(item.get("onde") or "").strip()[:200],
    }


def _relatorio_fallback(sinais):
    """Relatório determinístico quando a IA falha/retorna lixo — nunca fica vazio."""
    itens = []
    for grupo in sinais.get("erros_grupos", [])[:5]:
        playbook = (grupo.get("playbooks") or [{}])[0]
        itens.append(
            {
                "titulo": playbook.get("titulo") or grupo["assinatura"][:120] or "Erro",
                "severidade": playbook.get("severidade", "medio"),
                "evidencia": "{} ocorrência(s) · logger {}".format(
                    grupo["ocorrencias"], grupo["logger"] or "—"
                ),
                "causa_provavel": playbook.get("causa")
                or "Erro recorrente; veja o traceback nos detalhes do registro.",
                "solucao": playbook.get("solucao")
                or "Investigar o traceback no admin (Registros de auditoria, ação=erro).",
                "onde": playbook.get("onde") or grupo.get("logger_cobre") or "",
            }
        )
    return {
        "severidade_geral": severidade_deterministica(sinais),
        "resumo": "Diagnóstico automático (a IA não respondeu). Base: contagens da trilha.",
        "itens": itens,
    }


def montar_relatorio(bruto, sinais):
    """Valida o JSON da IA e cai no determinístico quando ele não serve."""
    try:
        dados = json.loads(bruto or "")
    except (json.JSONDecodeError, TypeError):
        return _relatorio_fallback(sinais)
    if not isinstance(dados, dict):
        return _relatorio_fallback(sinais)

    severidade = str(dados.get("severidade_geral") or "").strip().lower()
    if severidade not in SEVERIDADES:
        severidade = severidade_deterministica(sinais)
    itens = [i for i in (_limpar_item(x) for x in (dados.get("itens") or [])) if i][:8]
    if not itens and sinais.get("erros_grupos"):
        # A IA não listou nada apesar de haver erro: usa o determinístico.
        return _relatorio_fallback(sinais)
    return {
        "severidade_geral": severidade,
        "resumo": str(dados.get("resumo") or "").strip()[:600],
        "itens": itens,
    }


async def _gerar(sinais):
    entrada = json.dumps(sinais, ensure_ascii=False, default=str)[:14000]
    resposta = await services.gerar_chat(
        "auditoria_diagnostico",
        messages=[
            {"role": "system", "content": _prompt_diagnostico()},
            {"role": "user", "content": entrada},
        ],
        response_format={"type": "json_object"},
        max_tokens=1400,
    )
    return _conteudo(resposta)


async def diagnostico(usuario, desde=None, ate=None, dias_padrao=7):
    """Gera o diagnóstico da janela. Nunca levanta exceção."""
    desde, ate = _janela(desde, ate, dias_padrao)
    try:
        sinais = await sync_to_async(coletar_sinais)(usuario, desde, ate)
        try:
            bruto = await _gerar(sinais)
            relatorio = montar_relatorio(bruto, sinais)
        except Exception:
            logger.exception("auditor_diagnostico: IA falhou; usando relatório determinístico")
            relatorio = _relatorio_fallback(sinais)
    except Exception:
        logger.exception("auditor_diagnostico: falha ao coletar sinais")
        return {"ok": False, "erro": "Não foi possível gerar o diagnóstico agora."}

    return {
        "ok": True,
        "periodo": sinais["periodo"],
        "severidade_geral": relatorio["severidade_geral"],
        "resumo": relatorio["resumo"],
        "itens": relatorio["itens"],
        "erros_total": sinais["erros_total"],
        "total_registros": sinais["total_registros"],
        "grupos": [
            {
                "logger": g["logger"],
                "assinatura": g["assinatura"],
                "ocorrencias": g["ocorrencias"],
            }
            for g in sinais["erros_grupos"]
        ],
        "picos": sinais["picos"],
        "http_status": sinais["http_status"],
        "marcos": sinais["marcos"],
    }
