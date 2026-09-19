"""Narrativa dos relatórios do evento (copiloto do organizador).

Transforma os números que já existem em `relatorios/graficos.py` num **resumo**
e em **ações recomendadas**, para o organizador ler em segundos. A IA só
interpreta os dados que foram calculados — ela não inventa números: o prompt
recebe um recorte dos indicadores e a saída é validada. Sem IA, cai num texto
determinístico montado a partir dos mesmos números.
"""

import json
import logging

from eventos import services

from . import graficos as agregacoes

logger = logging.getLogger("eventos.ia")


def _por_id(lista, chave):
    for item in lista:
        if item.get("id") == chave:
            return item
    return None


def fatos(evento):
    """Recorte compacto dos indicadores para o prompt (sem PII)."""
    kpis = {item["rotulo"]: {"valor": item["valor"], "sufixo": item.get("sufixo", "")}
            for item in agregacoes.kpis(evento)}
    gs = agregacoes.graficos(evento)

    ocupacao = _por_id(gs, "ocupacao_atividade") or {}
    ociosas = _por_id(gs, "vagas_ociosas") or {}
    comparecimento = _por_id(gs, "comparecimento") or {}
    publicacao = _por_id(gs, "publicacao") or {}
    perfil = [g for g in gs if str(g.get("id", "")).startswith("perfil_")]

    return {
        "evento": {
            "titulo": evento.title,
            "categoria": evento.get_categoria_display(),
            "inicio": evento.data_inicio.strftime("%d/%m/%Y"),
            "fim": evento.data_fim.strftime("%d/%m/%Y"),
        },
        "indicadores": kpis,
        "atividades_mais_procuradas": [
            {"titulo": titulo, "inscritos": inscritos, "vagas": vagas}
            for titulo, inscritos, vagas in zip(
                ocupacao.get("labels", []),
                ocupacao.get("series", [{}])[0].get("data", []) if ocupacao.get("series") else [],
                ocupacao.get("series", [{}, {}])[1].get("data", []) if len(ocupacao.get("series", [])) > 1 else [],
            )
        ][:8],
        "vagas_ociosas": [
            {"titulo": titulo, "vagas_livres": valor}
            for titulo, valor in zip(
                ociosas.get("labels", []),
                ociosas.get("series", [{}])[0].get("data", []) if ociosas.get("series") else [],
            )
        ][:8],
        "comparecimento_total": {
            "presentes": sum(comparecimento.get("series", [{}])[0].get("data", []) if comparecimento.get("series") else []),
            "ausentes": sum(comparecimento.get("series", [{}, {}])[1].get("data", []) if len(comparecimento.get("series", [])) > 1 else []),
        },
        "publicacao": dict(zip(publicacao.get("labels", []),
                               (publicacao.get("series", [{}])[0].get("data", []) if publicacao.get("series") else []))),
        "perfil_inscritos": [
            {"titulo": g.get("titulo"), "rotulos": g.get("labels", []),
             "valores": (g.get("series", [{}])[0].get("data", []) if g.get("series") else [])}
            for g in perfil
        ],
    }


def _prompt(dados):
    return """Você é analista de eventos de um campus do IFMG e ajuda o organizador a
interpretar os números de um evento. NÃO invente dados: use apenas o que está no
JSON abaixo. Escreva em português, de forma objetiva e prática.

Dados do evento (JSON):
{dados}

Responda SOMENTE com JSON neste formato:
{{"resumo": "<2 a 3 frases>",
  "destaques": ["<ponto positivo ou atenção>", "..."],
  "acoes": ["<ação recomendada, concreta>", "..."]}}

Regras:
1. No máximo 4 destaques e 4 ações.
2. Cada ação deve ser executável pelo organizador (ex.: divulgar, publicar, ajustar vagas).
3. Se não houver dados suficientes, diga isso no resumo e deixe as listas vazias.""".format(
        dados=json.dumps(dados, ensure_ascii=False)
    )


def _limpar_lista(valor, limite=4):
    itens = []
    for item in valor or []:
        texto = " ".join(str(item or "").split())[:220]
        if texto:
            itens.append(texto)
        if len(itens) >= limite:
            break
    return itens


def narrativa_basica(dados):
    """Resumo e ações determinísticos (sem IA)."""
    indicadores = {chave: item["valor"] for chave, item in dados["indicadores"].items()}
    inscricoes = indicadores.get("Inscrições", 0)
    atividades = indicadores.get("Atividades", 0)
    ocupacao = indicadores.get("Ocupação média", 0)
    comparecimento = indicadores.get("Comparecimento", 0)
    rascunhos = indicadores.get("Rascunhos", 0)
    conflitos = indicadores.get("Conflitos na grade", 0)

    resumo = (
        "O evento tem %s atividade(s) e %s inscrição(ões), com ocupação média de %s%%."
        % (atividades, inscricoes, ocupacao)
    )
    if comparecimento:
        resumo += " O comparecimento até agora é de %s%%." % comparecimento

    destaques, acoes = [], []
    if dados.get("vagas_ociosas"):
        destaques.append("Há atividades com vagas ociosas.")
        nomes = ", ".join(item["titulo"] for item in dados["vagas_ociosas"][:3])
        acoes.append("Divulgar as atividades com vagas livres: %s." % nomes)
    if rascunhos:
        destaques.append("%s atividade(s) seguem como rascunho." % rascunhos)
        acoes.append("Revisar e publicar as atividades em rascunho.")
    if conflitos:
        destaques.append("Há %s conflito(s) na grade de horários." % conflitos)
        acoes.append("Resolver os conflitos de horário/local na programação.")
    if comparecimento and comparecimento < 50 and inscricoes:
        acoes.append("Reforçar a confirmação de presença (lembrete antes do evento).")

    return {
        "resumo": resumo,
        "destaques": destaques[:4],
        "acoes": acoes[:4],
        "origem": "heuristica",
        "aviso": "",
    }


async def narrar(evento):
    """Narra os relatórios do evento (IA) com fallback determinístico."""
    dados = await _fatos_async(evento)
    try:
        resposta = await services.gerar_chat(
            "relatorio_narrado",
            messages=[{"role": "system", "content": _prompt(dados)}],
            response_format={"type": "json_object"},
            max_tokens=700,
            temperature=0.3,
        )
        bruto = json.loads(resposta.choices[0].message.content or "{}")
        resumo = " ".join(str(bruto.get("resumo") or "").split())[:900]
        destaques = _limpar_lista(bruto.get("destaques"))
        acoes = _limpar_lista(bruto.get("acoes"))
        if not resumo:
            return narrativa_basica(dados)
        return {"resumo": resumo, "destaques": destaques, "acoes": acoes,
                "origem": "ia", "aviso": ""}
    except Exception as erro:  # noqa: BLE001 - IA é acessória
        resultado = narrativa_basica(dados)
        resultado["aviso"] = "A IA não está disponível agora; usei a leitura automática (%s)." % erro
        return resultado


async def _fatos_async(evento):
    from asgiref.sync import sync_to_async

    return await sync_to_async(fatos)(evento)
