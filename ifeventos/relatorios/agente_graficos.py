"""Agente de visualizações: curadoria e insights dos gráficos (copiloto).

O organizador pode pedir "quais gráficos mostrar?" (curadoria) ou um "insight"
sobre os gráficos já exibidos. O agente só **escolhe do catálogo** de gráficos
que o servidor sabe montar (`agregacoes.graficos_alunos`/`graficos.py`) e
comenta os números que já existem — nunca inventa agregação nem dado. Sem IA,
cai num fallback determinístico.
"""

import json
import logging

from eventos import ia_config, services

logger = logging.getLogger("eventos.ia")

MAX_GRAFICOS = 6


def _prompt_curadoria(evento, disponiveis, perfil):
    return """Você é o copiloto de um organizador de eventos de um campus do IFMG.

Evento: {titulo} (tema: {categoria})
Perfil dos dados: {perfil}

Gráficos disponíveis (escolha APENAS por id, do mais útil para o menos útil):
{disponiveis}

Escolha no máximo {maximo} gráficos que ajudem a entender a participação e o
comparecimento. Responda SOMENTE com JSON:
{{"ids": ["<id>"], "legenda": "<uma frase explicando a escolha>"}}""".format(
        titulo=evento.title,
        categoria=evento.get_categoria_display(),
        perfil=json.dumps(perfil, ensure_ascii=False),
        disponiveis="\n".join("- %s: %s" % (g["id"], g["titulo"]) for g in disponiveis),
        maximo=MAX_GRAFICOS,
    )


def _limpar_ids(ids, validos):
    limpos = []
    for valor in ids or []:
        valor = str(valor or "").strip()
        if valor in validos and valor not in limpos:
            limpos.append(valor)
    return limpos[:MAX_GRAFICOS]


def curadoria_basica(disponiveis):
    """Fallback: usa a ordem do catálogo (o servidor já a monta por relevância)."""
    return {
        "ids": [g["id"] for g in disponiveis][:MAX_GRAFICOS],
        "legenda": "Seleção automática com os gráficos mais informativos.",
        "origem": "heuristica",
        "aviso": "",
    }


async def curar(evento, disponiveis, perfil):
    """Escolhe, entre os gráficos disponíveis, os mais úteis para o organizador."""
    validos = [g["id"] for g in disponiveis]
    if not validos:
        return {"ids": [], "legenda": "", "origem": None, "aviso": "Sem gráficos."}
    try:
        resposta = await services.gerar_chat(
            "graficos_curadoria",
            messages=[{"role": "system", "content": _prompt_curadoria(evento, disponiveis, perfil)}],
            response_format={"type": "json_object"},
            max_tokens=400,
            temperature=0,
        )
        dados = json.loads(resposta.choices[0].message.content or "{}")
        ids = _limpar_ids(dados.get("ids"), validos)
        if not ids:
            return curadoria_basica(disponiveis)
        legenda = " ".join(str(dados.get("legenda") or "").split())[:220]
        return {"ids": ids, "legenda": legenda, "origem": "ia", "aviso": ""}
    except Exception as erro:  # noqa: BLE001 - IA é acessória
        resultado = curadoria_basica(disponiveis)
        resultado["aviso"] = "A IA não está disponível agora (%s)." % erro
        return resultado


def _prompt_insights(evento, graficos):
    return """Você é analista de eventos de um campus do IFMG. Comente os gráficos
abaixo usando SOMENTE os números fornecidos; não invente dados.

Evento: {titulo}

Gráficos (JSON):
{graficos}

Responda SOMENTE com JSON: {{"insights": [{{"id": "<id>", "texto": "<1 frase>"}}]}}""".format(
        titulo=evento.title,
        graficos=json.dumps(graficos, ensure_ascii=False),
    )


def _prompt_grafico_por_descricao(evento, disponiveis, texto):
    return """Você é o copiloto de um organizador de eventos de um campus do IFMG.

Evento: {titulo}

O organizador pediu um gráfico com as seguintes palavras: "{texto}".

Gráficos disponíveis (escolha APENAS por id):
{disponiveis}

Escolha o gráfico que melhor atende ao pedido. Se nada casar, escolha o mais
próximo. Responda SOMENTE com JSON:
{{"id": "<id>", "legenda": "<uma frase curta explicando a escolha>"}}""".format(
        titulo=evento.title,
        texto=(texto or "").strip()[:300],
        disponiveis="\n".join("- %s: %s" % (g["id"], g["titulo"]) for g in disponiveis),
    )


def grafico_por_descricao_basico(disponiveis, texto):
    """Fallback: casa palavras do pedido com os títulos; senão usa o primeiro."""
    termos = [t.lower() for t in (texto or "").split() if len(t) > 2]
    for grafico in disponiveis:
        titulo = (grafico.get("titulo") or "").lower()
        if termos and any(termo in titulo for termo in termos):
            return grafico
    return (disponiveis or [None])[0]


async def grafico_por_descricao(evento, disponiveis, texto):
    """Devolve o spec de gráfico que atende ao pedido em linguagem natural.

    A IA escolhe um gráfico do catálogo montado pelo servidor; sem IA, o fallback
    casa palavras do pedido com os títulos. Nunca inventa gráfico nem número.
    """
    if not disponiveis:
        return {"id": None, "legenda": "", "origem": None, "aviso": "Sem gráficos."}
    if not (texto or "").strip():
        escolhido = grafico_por_descricao_basico(disponiveis, texto)
        return {
            "id": escolhido["id"], "legenda": "Gráfico sugerido automaticamente.",
            "origem": "heuristica", "aviso": "",
        }
    try:
        resposta = await services.gerar_chat(
            "graficos_nl",
            messages=[{
                "role": "system",
                "content": _prompt_grafico_por_descricao(evento, disponiveis, texto),
            }],
            response_format={"type": "json_object"},
            max_tokens=400,
            temperature=0,
        )
        dados = json.loads(resposta.choices[0].message.content or "{}")
        escolhido_id = str(dados.get("id") or "").strip()
        validos = {g["id"] for g in disponiveis}
        if escolhido_id in validos:
            legenda = " ".join(str(dados.get("legenda") or "").split())[:220]
            return {"id": escolhido_id, "legenda": legenda, "origem": "ia", "aviso": ""}
        escolhido = grafico_por_descricao_basico(disponiveis, texto)
        return {
            "id": escolhido["id"], "legenda": "Gráfico sugerido automaticamente.",
            "origem": "heuristica", "aviso": "",
        }
    except Exception as erro:  # noqa: BLE001 - IA é acessória
        escolhido = grafico_por_descricao_basico(disponiveis, texto)
        return {
            "id": escolhido["id"], "legenda": "Gráfico sugerido automaticamente.",
            "origem": "heuristica",
            "aviso": "A IA não está disponível agora (%s)." % erro,
        }


def insights_basico(graficos):
    """Fallback: um comentário simples por gráfico, com o maior valor."""
    itens = []
    for grafico in graficos or []:
        series = grafico.get("series") or []
        dados = series[0].get("data") if series else []
        if dados and grafico.get("labels"):
            indice = max(range(len(dados)), key=lambda i: dados[i])
            itens.append({
                "id": grafico["id"],
                "texto": "Maior valor em %s: %s." % (
                    grafico["labels"][indice], dados[indice]
                ),
            })
    return {"insights": itens, "origem": "heuristica", "aviso": ""}


async def insights(evento, graficos):
    """Um comentário curto por gráfico, ancorado nos números."""
    if not graficos:
        return {"insights": [], "origem": None, "aviso": "Sem gráficos."}
    try:
        resposta = await services.gerar_chat(
            "graficos_insights",
            messages=[{"role": "system", "content": _prompt_insights(evento, graficos)}],
            response_format={"type": "json_object"},
            max_tokens=600,
            temperature=0.3,
        )
        dados = json.loads(resposta.choices[0].message.content or "{}")
        validos = {g["id"] for g in graficos}
        itens = [
            {"id": item.get("id"), "texto": " ".join(str(item.get("texto") or "").split())[:240]}
            for item in (dados.get("insights") or [])
            if isinstance(item, dict) and item.get("id") in validos
        ]
        if not itens:
            return insights_basico(graficos)
        return {"insights": itens, "origem": "ia", "aviso": ""}
    except Exception as erro:  # noqa: BLE001 - IA é acessória
        resultado = insights_basico(graficos)
        resultado["aviso"] = "A IA não está disponível agora (%s)." % erro
        return resultado
