"""Pré-triagem de propostas da chamada (copiloto do organizador).

Ajuda o organizador a decidir a fila de propostas pendentes: calcula sinais
objetivos (conflitos, tipo faltando, vagas acima da capacidade, descrição fraca,
quase-duplicatas) e, quando a IA está ligada, pede uma sugestão de decisão com
justificativa. **Nada é decidido aqui**: o resultado é uma sugestão que o
organizador confirma nas telas normais (`propostas.aprovar`/`rejeitar`).

Regras de ouro desta camada:

- Nada de PII no dossiê enviado ao modelo (sem nome/e-mail/CPF/telefone/endereço).
- Toda saída do modelo passa por validação/sanitização (score, enum, catálogo).
- Sem IA (chave ausente, `IA_ATIVA=False` ou erro), cai no fallback determinístico
  e a tela continua funcionando.
- O resultado é cacheado por uma assinatura das propostas; reanalisar força nova
  consulta.
"""

import difflib
import hashlib
import json
import logging
import re

from django.core.cache import cache
from django.utils import timezone
from asgiref.sync import sync_to_async

from . import propostas as propostas_mod
from . import services
from . import contexto_ia
from . import ia_config
from .models import Atividade, TipoAtividade, sem_acento

logger = logging.getLogger("eventos.ia")

# Quantas propostas por chamada à OpenAI (dossiês longos demais por lote).
TRIAGEM_LOTE = 20

# Teto da descrição enviada ao modelo (custo/contexto).
TRIAGEM_DESCRICAO_MAX = 600

# Quanto tempo a triagem de um evento fica em cache.
TRIAGEM_CACHE_SEGUNDOS = 3600

# Similaridade mínima para considerar duas propostas "quase-duplicatas".
TRIAGEM_LIMIAR_DUPLICATA = 0.62

DECISOES = {"aprovar", "revisar", "rejeitar"}


# ---------------------------------------------------------------------------
# Camada 1 — sinais objetivos (sem IA)
# ---------------------------------------------------------------------------

def _tokens(texto):
    return set(re.findall(r"\w+", sem_acento(texto or "")))


def _similaridade(a, b):
    """Semelhança 0..1 entre dois textos (Jaccard de palavras + sequência)."""
    if not a or not b:
        return 0.0
    ta, tb = _tokens(a), _tokens(b)
    jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    sequencia = difflib.SequenceMatcher(None, sem_acento(a), sem_acento(b)).ratio()
    return max(jaccard, sequencia)


def detectar_duplicatas(dossies, limiar=TRIAGEM_LIMIAR_DUPLICATA):
    """Marca quase-duplicatas entre as propostas (relação simétrica).

    Compara o texto (título + descrição). Devolve {proposta_id: [ids]}.
    """
    relacionados = {}
    for i, a in enumerate(dossies):
        for b in dossies[i + 1:]:
            texto_a = "%s %s" % (a.get("titulo", ""), a.get("descricao", ""))
            texto_b = "%s %s" % (b.get("titulo", ""), b.get("descricao", ""))
            if _similaridade(texto_a, texto_b) >= limiar:
                relacionados.setdefault(a["proposta_id"], []).append(b["proposta_id"])
                relacionados.setdefault(b["proposta_id"], []).append(a["proposta_id"])
    return {chave: sorted(valor) for chave, valor in relacionados.items()}


def alertas_objetivos(proposta, evento, tipos_por_chave):
    """Lista de avisos objetivos (texto) sobre uma proposta pendente."""
    alertas = []

    conflitos = propostas_mod.conflitos(
        evento,
        proposta.data_hora_inicio,
        proposta.data_hora_fim,
        local=proposta.local,
        palestrantes=list(proposta.palestrantes.all()),
        ignorar=proposta,
        vaga=proposta.vaga,
    )
    for aviso in conflitos:
        atividade = aviso["atividade"]
        alvo = "'%s' (%s)" % (atividade.titulo, atividade.quando_legivel)
        if aviso["tipo"] == "espaco":
            alertas.append("Choque de espaço com %s." % alvo)
        else:
            alertas.append("%s já tem atividade nesse horário: %s." % (aviso["rotulo"], alvo))

    if not proposta.tipo_id:
        nome, existente = services.sugerir_tipo_por_palavras(
            proposta.titulo, proposta.descricao,
            [item["nome"] for item in tipos_por_chave.values()],
        )
        if nome:
            encontrado = tipos_por_chave.get(sem_acento(nome))
            if encontrado and existente:
                alertas.append("Sem tipo definido — sugerido do catálogo: %s." % encontrado["nome"])
            elif nome:
                alertas.append("Sem tipo definido — sugestão: %s." % nome)
        else:
            alertas.append("Sem tipo definido (há apenas um tipo sugerido em texto livre).")

    espaco = proposta.vaga.espaco if proposta.vaga_id and proposta.vaga.espaco_id else None
    if espaco and espaco.capacidade and proposta.n_vagas > espaco.capacidade:
        alertas.append(
            "Nº de vagas (%s) acima da capacidade do espaço (%s)."
            % (proposta.n_vagas, espaco.capacidade)
        )

    if len((proposta.descricao or "").strip()) < 40:
        alertas.append("Descrição muito curta — pode faltar contexto ao público.")

    detectada = services.sugerir_categoria_por_palavras(
        proposta.titulo, proposta.descricao, list(services.CATEGORIA_PALAVRAS.keys())
    )
    if detectada and sem_acento(detectada) != sem_acento(evento.categoria):
        alertas.append(
            "Tema detectado (%s) difere da categoria do evento." % detectada
        )

    return alertas


def montar_dossie(proposta, evento, tipos_por_chave):
    """Dossiê de UMA proposta para a triagem — SEM dados pessoais."""
    espaco = proposta.vaga.espaco if proposta.vaga_id and proposta.vaga.espaco_id else None
    dossie = {
        "proposta_id": proposta.pk,
        "titulo": proposta.titulo,
        "descricao": (proposta.descricao or "").strip()[:TRIAGEM_DESCRICAO_MAX],
        "tipo_nome": proposta.tipo.nome if proposta.tipo_id else "",
        "tipo_sugerido": proposta.tipo_sugerido or "",
        "quando": proposta.quando_legivel,
        "espaco": espaco.nome if espaco else (proposta.local or ""),
        "n_vagas": proposta.n_vagas,
        "capacidade": espaco.capacidade if espaco else None,
        "emite_certificado": bool(proposta.emite_certificado),
        "alertas": alertas_objetivos(proposta, evento, tipos_por_chave),
        "duplicata_de": [],
    }
    # Chave interna (prefixo "_"): não vai no prompt nem na resposta, só alimenta
    # a heurística de tipo quando a IA não devolve um id.
    dossie["_tipo_id_heuristica"] = sugerir_tipo_id(dossie, tipos_por_chave)
    return dossie


def sugerir_tipo_id(dossie, tipos_por_chave):
    """Id do tipo do catálogo mais provável para o dossiê (ou None)."""
    if dossie.get("tipo_nome"):
        return None
    nome, _existente = services.sugerir_tipo_por_palavras(
        dossie.get("titulo", ""), dossie.get("descricao", ""),
        [item["nome"] for item in tipos_por_chave.values()],
    )
    encontrado = tipos_por_chave.get(sem_acento(nome)) if nome else None
    return encontrado["id"] if encontrado else None


def score_heuristica(dossie):
    """Score determinístico 0..100 a partir dos sinais objetivos."""
    score = 70
    if dossie.get("tipo_nome") or dossie.get("tipo_sugerido"):
        score += 10
    elif dossie.get("_tipo_id_heuristica"):
        score += 5
    if len(dossie.get("descricao", "")) >= 120:
        score += 15
    for alerta in dossie.get("alertas", []):
        if alerta.startswith("Choque de espaço"):
            score -= 20
        elif "já tem atividade nesse horário" in alerta:
            score -= 15
        elif "acima da capacidade" in alerta:
            score -= 10
        elif alerta.startswith("Descrição muito curta"):
            score -= 10
    return max(0, min(100, score))


def decisao_heuristica(dossie):
    """(score, decisao, justificativa) sem IA."""
    score = score_heuristica(dossie)
    tem_conflito = any(
        alerta.startswith("Choque de espaço") or "já tem atividade nesse horário" in alerta
        for alerta in dossie.get("alertas", [])
    )
    if tem_conflito:
        decisao = "revisar"
        justificativa = "Há conflito de agenda; confirme se é intencional antes de aprovar."
    elif dossie.get("alertas"):
        decisao = "revisar"
        justificativa = " ".join(dossie["alertas"])
    else:
        decisao = "aprovar"
        justificativa = "Sem conflitos e com informações suficientes para a programação."
    return score, decisao, justificativa


# ---------------------------------------------------------------------------
# Camada 2 — sugestão por IA
# ---------------------------------------------------------------------------

def _prompt(dossies, evento, tipos, dossie_texto=""):
    catalogo = ", ".join("%s (id %s)" % (t.nome, t.pk) for t in tipos) or "(nenhum)"
    return """Você ajuda a ORGANIZAR (não decide) a pré-triagem das propostas de atividades de um evento de um campus do IFMG.

=== CONTEXTO DO BANCO ===
{dossie}
=== FIM DO CONTEXTO ===

Evento: {titulo}
Categoria/tema do evento: {categoria}
Tipos de atividade do catálogo: {catalogo}

Para cada proposta abaixo, avalie a aderência ao tema do evento e a qualidade da
proposta, e SUGIRA uma decisão ao organizador. Você NÃO decide nada.

Sinais objetivos já calculados (use como verdade): "alertas" e "duplicata_de".

Propostas (JSON):
{dossies}

Regras:
1. "decisao" só pode ser "aprovar", "revisar" ou "rejeitar".
2. "score" é um inteiro de 0 a 100 (aderência + qualidade + ausência de conflito).
3. Se houver conflito de agenda, prefira "revisar".
4. "tipo_sugerido_id": use um id do catálogo quando fizer sentido; senão null.
5. "qualidade_descricao": "boa", "regular" ou "fraca".
6. Se a decisão for "rejeitar", preencha "motivo_rejeicao_sugerido"; senão "".
7. "justificativa": uma frase curta, objetiva, em português.

Responda SOMENTE com JSON neste formato:
{{"itens": [{{"proposta_id": 1, "score": 80, "decisao": "aprovar",
  "justificativa": "...", "tipo_sugerido_id": null, "qualidade_descricao": "boa",
  "motivo_rejeicao_sugerido": ""}}]}}""".format(
        dossie=dossie_texto,
        titulo=evento.title,
        categoria=evento.get_categoria_display(),
        catalogo=catalogo,
        dossies=json.dumps([
            {k: v for k, v in dossie.items() if not k.startswith("_")}
            for dossie in dossies
        ], ensure_ascii=False),
    )


def sanitizar_item(bruto, dossie, ids_tipos):
    """Valida/sanitiza a sugestão da IA para UMA proposta.

    Começa pela heurística e SOBRESCREVE com os campos válidos do modelo — assim
    um retorno parcial ou inválido nunca piora o resultado.
    """
    score, decisao, justificativa = decisao_heuristica(dossie)
    item = {
        "proposta_id": dossie["proposta_id"],
        "score": score,
        "decisao": decisao,
        "justificativa": justificativa,
        "tipo_sugerido_id": dossie.get("_tipo_id_heuristica"),
        "tipo_sugerido_nome": "",
        "qualidade_descricao": "regular",
        "motivo_rejeicao_sugerido": "",
        "alertas": dossie.get("alertas", []),
        "duplicata_de": dossie.get("duplicata_de", []),
        "origem": "heuristica",
    }
    if not isinstance(bruto, dict):
        return item

    try:
        valor = int(bruto.get("score"))
        item["score"] = max(0, min(100, valor))
    except (TypeError, ValueError):
        pass

    decisao_ia = str(bruto.get("decisao") or "").strip().lower()
    if decisao_ia in DECISOES:
        item["decisao"] = decisao_ia

    justificativa_ia = " ".join(str(bruto.get("justificativa") or "").split())[:220]
    if justificativa_ia:
        item["justificativa"] = justificativa_ia

    qualidade = str(bruto.get("qualidade_descricao") or "").strip().lower()
    if qualidade in {"boa", "regular", "fraca"}:
        item["qualidade_descricao"] = qualidade

    motivo = " ".join(str(bruto.get("motivo_rejeicao_sugerido") or "").split())[:220]
    if item["decisao"] == "rejeitar":
        item["motivo_rejeicao_sugerido"] = motivo

    tipo_id = bruto.get("tipo_sugerido_id")
    if isinstance(tipo_id, int) and tipo_id in ids_tipos:
        item["tipo_sugerido_id"] = tipo_id

    item["origem"] = "ia"
    return item


async def _chamar_ia(dossies, evento, tipos, dossie_texto=""):
    """Pede ao modelo a análise de um lote de dossiês. Levanta em caso de erro."""
    client = services.get_openai_client()
    kwargs = await ia_config.chamada_kwargs_async("triagem_propostas", max_tokens=2000, temperature=0)
    resposta = await client.chat.completions.create(
        messages=[{"role": "system", "content": _prompt(dossies, evento, tipos, dossie_texto)}],
        response_format={"type": "json_object"},
        **kwargs,
    )
    services.registrar_uso_ia("triagem_propostas", kwargs["model"], resposta)
    dados = json.loads(resposta.choices[0].message.content or "{}")
    return dados.get("itens") or []


# ---------------------------------------------------------------------------
# Orquestração (dossiês + IA + cache)
# ---------------------------------------------------------------------------

def coletar_dossies(evento):
    """Monta os dossiês das propostas pendentes do evento (acesso ao banco)."""
    lista = list(
        propostas_mod.pendentes([evento])
        .select_related("tipo", "vaga", "vaga__espaco")
        .prefetch_related("palestrantes")
    )
    tipos_por_chave = {
        sem_acento(tipo.nome): {"id": tipo.pk, "nome": tipo.nome}
        for tipo in TipoAtividade.objects.order_by("nome")
    }
    dossies = [montar_dossie(proposta, evento, tipos_por_chave) for proposta in lista]

    duplicatas = detectar_duplicatas(dossies)
    for dossie in dossies:
        dossie["duplicata_de"] = duplicatas.get(dossie["proposta_id"], [])
    return dossies


def _assinatura(evento, dossies):
    partes = ["%s:%s" % (d["proposta_id"], d.get("quando", "")) for d in dossies]
    partes.append(sem_acento(evento.categoria or ""))
    partes.append(sem_acento(evento.title or ""))
    return hashlib.md5("|".join(partes).encode("utf-8")).hexdigest()


async def analisar_evento(evento, forcar=False):
    """Triagem completa do evento, com cache. Não decide nada — só sugere."""
    dossies = await sync_to_async(coletar_dossies)(evento)
    analisado_em = timezone.now().isoformat()

    if not dossies:
        return {
            "origem": None,
            "aviso": "Nenhuma proposta aguardando análise.",
            "analisado_em": analisado_em,
            "itens": [],
        }

    chave = "triagem_evento_%s_%s" % (evento.pk, _assinatura(evento, dossies))
    if not forcar:
        cacheado = await sync_to_async(cache.get)(chave)
        if cacheado:
            return cacheado

    tipos = await sync_to_async(list)(TipoAtividade.objects.order_by("nome"))
    ids_tipos = {tipo.pk for tipo in tipos}
    nome_por_id = {tipo.pk: tipo.nome for tipo in tipos}
    dossie_texto = contexto_ia.resumo_texto(
        await sync_to_async(contexto_ia.dossie)(evento)
    )

    itens, aviso = [], ""
    try:
        for inicio in range(0, len(dossies), TRIAGEM_LOTE):
            lote = dossies[inicio:inicio + TRIAGEM_LOTE]
            retorno = await _chamar_ia(lote, evento, tipos, dossie_texto)
            por_id = {
                item.get("proposta_id"): item
                for item in retorno if isinstance(item, dict)
            }
            for dossie in lote:
                bruto = por_id.get(dossie["proposta_id"], {})
                item = sanitizar_item(bruto, dossie, ids_tipos)
                item["tipo_sugerido_nome"] = nome_por_id.get(item["tipo_sugerido_id"], "")
                itens.append(item)
        origem = "ia"
    except Exception as erro:  # noqa: BLE001 - IA é acessória; nunca derruba a tela
        logger.warning("triagem: IA indisponível, usando heurística (%s)", erro)
        itens = [sanitizar_item({}, dossie, ids_tipos) for dossie in dossies]
        for item in itens:
            item["tipo_sugerido_nome"] = nome_por_id.get(item["tipo_sugerido_id"], "")
        origem = "heuristica"
        aviso = "A IA não está disponível agora; usei a análise por regras."

    resultado = {
        "origem": origem,
        "aviso": aviso,
        "analisado_em": analisado_em,
        "itens": itens,
    }
    await sync_to_async(cache.set)(chave, resultado, TRIAGEM_CACHE_SEGUNDOS)
    return resultado
