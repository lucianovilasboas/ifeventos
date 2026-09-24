"""Agente interno de auditoria ("AuditorIA").

Traduz uma pergunta em linguagem natural numa **consulta estruturada** (JSON),
executa essa consulta **no ORM** (sem SQL livre) e resume o resultado em texto.

Segurança: o LLM nunca recebe dados crus nem escreve SQL/ORM. Ele só devolve um
objeto com filtros/agrupamento/limite, validados contra listas e limites; a
consulta roda com o **escopo do usuário** (staff vê tudo; organizador vê os seus
eventos/ações). É o oposto de "text-to-SQL".
"""

from __future__ import annotations

import json
import logging
import re

from asgiref.sync import sync_to_async
from django.db.models import Count, Q

from . import auditoria, services
from .models import RegistroAuditoria

logger = logging.getLogger("eventos.ia")

_AGRUPAMENTOS = {"acao", "entidade", "origem", "dia"}
_RE_ACAO = re.compile(r"^[a-z_]{1,30}$")
_RE_ENTIDADE = re.compile(r"^[A-Za-z]{1,60}$")
_RE_ORIGEM = re.compile(r"^[a-z]{1,10}$")


def _opcoes():
    acoes = ", ".join(c[0] for c in RegistroAuditoria.ACAO_CHOICES)
    origens = ", ".join(c[0] for c in RegistroAuditoria.ORIGEM_CHOICES)
    return acoes, origens


def _prompt_especificacao():
    from django.utils import timezone

    acoes, origens = _opcoes()
    return (
        "Você traduz perguntas sobre o histórico de ações (auditoria) do sistema "
        "numa CONSULTA ESTRUTURADA. Responda SOMENTE com JSON válido no formato:\n"
        '{"filtros": {"acao": "", "entidade": "", "origem": "", "desde": "", '
        '"ate": "", "search": "", "evento": null, "usuario": null}, '
        '"agrupar_por": "acao|entidade|origem|dia|null", "limite": 20}\n'
        "Regras:\n"
        "- Preencha apenas o que a pergunta pede; deixe o resto vazio/null.\n"
        f"- acao válidas: {acoes}.\n"
        "- entidade é o nome do modelo: Evento, Atividade, Inscricao, Presenca, "
        "Certificado, ConfiguracaoCertificado, Espaco, Vaga, ChamadaProposicoes, "
        "Participante.\n"
        f"- origem: {origens}.\n"
        "- Datas em YYYY-MM-DD. Hoje é " + timezone.localdate().isoformat() + ".\n"
        '- Use "agrupar_por" quando pedirem totais/contagens/por dia/por pessoa.\n'
        '- "limite" entre 1 e 100.\n'
        "Não escreva nada fora do JSON."
    )


_PROMPT_RESPOSTA = (
    "Você responde em português, em 1 a 4 frases, sobre o histórico de ações "
    "(auditoria) do sistema. Recebe a pergunta, a consulta executada e o "
    "resultado (JSON). Baseie-se SOMENTE no resultado; se vier vazio, diga que "
    "não encontrou registros para o período/filtro. Não invente números. Os "
    "e-mails já vêm mascarados — não tente desmascarar."
)


def _conteudo(resposta) -> str:
    try:
        return (resposta.choices[0].message.content or "").strip()
    except Exception:
        return ""


def normalizar_spec(spec) -> dict:
    """Valida/normaliza a consulta proposta pelo modelo (allowlist + limites)."""
    if not isinstance(spec, dict):
        spec = {}
    filtros = spec.get("filtros")
    if not isinstance(filtros, dict):
        filtros = {}

    limpos = {}
    acao = str(filtros.get("acao") or "").strip().lower()
    if _RE_ACAO.match(acao):
        limpos["acao"] = acao
    entidade = str(filtros.get("entidade") or "").strip()
    if _RE_ENTIDADE.match(entidade):
        limpos["entidade"] = entidade
    origem = str(filtros.get("origem") or "").strip().lower()
    if _RE_ORIGEM.match(origem):
        limpos["origem"] = origem
    for chave in ("desde", "ate", "search"):
        valor = filtros.get(chave)
        if isinstance(valor, str) and valor.strip():
            limpos[chave] = valor.strip()[:60]
    for chave in ("evento", "usuario"):
        valor = filtros.get(chave)
        if isinstance(valor, bool):
            continue
        if isinstance(valor, int):
            limpos[chave] = valor
        elif isinstance(valor, str) and valor.isdigit():
            limpos[chave] = int(valor)

    agrupar = spec.get("agrupar_por")
    if agrupar not in _AGRUPAMENTOS:
        agrupar = None
    try:
        limite = int(spec.get("limite"))
    except (TypeError, ValueError):
        limite = 20
    limite = max(1, min(limite, 100))

    return {"filtros": limpos, "agrupar_por": agrupar, "limite": limite}


def executar_consulta(spec, usuario) -> dict:
    """Roda a consulta validada no ORM, com o escopo do usuário."""
    filtros = spec.get("filtros") or {}
    base = auditoria.escopo_para_usuario(RegistroAuditoria.objects.all(), usuario)

    if filtros.get("acao"):
        base = base.filter(acao=filtros["acao"])
    if filtros.get("entidade"):
        base = base.filter(entidade=filtros["entidade"])
    if filtros.get("origem"):
        base = base.filter(origem=filtros["origem"])
    if filtros.get("evento"):
        base = base.filter(evento_id=filtros["evento"])
    if filtros.get("usuario"):
        base = base.filter(usuario_id=filtros["usuario"])

    desde = auditoria.limite_data(filtros.get("desde"))
    if desde:
        base = base.filter(criado_em__gte=desde)
    ate = auditoria.limite_data(filtros.get("ate"), fim=True)
    if ate:
        base = base.filter(criado_em__lte=ate)

    if filtros.get("search"):
        termo = filtros["search"]
        base = base.filter(
            Q(resumo__icontains=termo)
            | Q(objeto_repr__icontains=termo)
            | Q(usuario_nome__icontains=termo)
        )

    limite = spec.get("limite") or 20
    agrupar = spec.get("agrupar_por")
    if agrupar:
        campo = "criado_em__date" if agrupar == "dia" else agrupar
        grupos = list(
            base.values(campo).annotate(total=Count("id")).order_by("-total")[:limite]
        )
        return {"agrupado_por": agrupar, "total": base.count(), "grupos": grupos}

    itens = [
        {
            "criado_em": r.criado_em.isoformat() if r.criado_em else None,
            "usuario": r.usuario_nome,
            "acao": r.acao,
            "entidade": r.entidade,
            "objeto": r.objeto_repr or r.objeto_id,
            "evento": r.evento_id,
            "origem": r.origem,
            "resumo": r.resumo,
            "detalhes": r.detalhes,
        }
        for r in base.order_by("-criado_em")[:limite]
    ]
    return {"agrupado_por": None, "total": base.count(), "itens": itens}


async def _especificar(pergunta: str) -> dict:
    resposta = await services.gerar_chat(
        "auditoria",
        messages=[
            {"role": "system", "content": _prompt_especificacao()},
            {"role": "user", "content": pergunta},
        ],
        response_format={"type": "json_object"},
        max_tokens=400,
    )
    try:
        bruto = json.loads(_conteudo(resposta) or "{}")
    except json.JSONDecodeError:
        bruto = {}
    return normalizar_spec(bruto)


async def _resumir(pergunta: str, spec: dict, resultado: dict) -> str:
    entrada = json.dumps(
        {"pergunta": pergunta, "consulta": spec, "resultado": resultado},
        ensure_ascii=False,
        default=str,
    )[:12000]
    resposta = await services.gerar_chat(
        "auditoria",
        messages=[
            {"role": "system", "content": _PROMPT_RESPOSTA},
            {"role": "user", "content": entrada},
        ],
        max_tokens=600,
    )
    return _conteudo(resposta)


async def responder(pergunta: str, usuario) -> dict:
    """Responde uma pergunta sobre a auditoria. Nunca levanta exceção."""
    pergunta = (pergunta or "").strip()
    if not pergunta:
        return {"ok": False, "erro": "Escreva uma pergunta sobre o histórico."}
    try:
        spec = await _especificar(pergunta)
        # A consulta é ORM (síncrono): roda num thread à parte.
        resultado = await sync_to_async(executar_consulta)(spec, usuario)
        texto = await _resumir(pergunta, spec, resultado)
    except Exception:
        logger.exception("auditor_ia: falha ao responder a pergunta")
        return {"ok": False, "erro": "Não foi possível consultar a auditoria agora."}
    return {
        "ok": True,
        "resposta": texto or "Não encontrei registros para essa pergunta.",
        "consulta": spec,
        "total": resultado.get("total", 0),
    }
