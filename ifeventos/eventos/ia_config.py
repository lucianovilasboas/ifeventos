"""Resolução do modelo de LLM por contexto (configurável no admin).

Cada ponto do sistema que usa IA tem uma `chave` fixa, listada em `CONTEXTOS`.
O modelo de cada contexto é lido do banco (`ContextoIA`, editável no admin) com
fallback para o padrão do ambiente (`settings.IA_MODELO_TEXTO` /
`IA_MODELO_CLASSIFICACAO`). O mapa é cacheado e invalidado ao salvar no admin.

Uso típico nos módulos de IA::

    cfg = ia_config.config("triagem_propostas")
    if not cfg["ativo"]:
        raise RuntimeError("contexto de IA desativado")
    modelo = cfg["modelo"]
    max_tokens = cfg["max_tokens"] or 1000
"""

from django.conf import settings
from django.core.cache import cache

import re

CACHE_KEY = "ia_config_contextos"
CACHE_TTL = 3600  # segurança; o admin invalida na hora

MODELOS_CACHE_KEY = "ia_openai_modelos"
MODELOS_TTL = 3600

# Modelos novos (gpt-5*, o-series) usam `max_completion_tokens` e não aceitam
# `temperature` custom. Os demais usam `max_tokens` e temperature normal.
_RE_MODELO_COMPLETION = re.compile(r"^(gpt-5|o[1-9])")

# Fragmentos que indicam modelo que NÃO é de chat (fica fora do datalist).
_MODELO_NAO_CHAT = (
    "embedding", "whisper", "tts", "dall-e", "moderation", "realtime",
    "transcribe", "audio", "image", "davinci", "babbage",
)


# Registro dos contextos conhecidos pelo CÓDIGO. A `chave` é o que os módulos
# usam em `config(...)`; o resto é rótulo/grupo/padrão exibido no admin.
CONTEXTOS = [
    {"chave": "mensagem_usuario", "rotulo": "Mensagem do dia", "grupo": "geral",
     "tipo_padrao": "texto", "ordem": 10},
    {"chave": "descricao_evento", "rotulo": "Descrição de evento/atividade",
     "grupo": "geral", "tipo_padrao": "texto", "ordem": 20},
    {"chave": "sugerir_categoria", "rotulo": "Sugerir tema do evento",
     "grupo": "organizador", "tipo_padrao": "classificacao", "ordem": 30},
    {"chave": "sugerir_tipo", "rotulo": "Sugerir tipo de atividade (proposta)",
     "grupo": "participante", "tipo_padrao": "classificacao", "ordem": 40},
    {"chave": "concierge", "rotulo": "Assistente da programação (participante)",
     "grupo": "participante", "tipo_padrao": "classificacao", "ordem": 50},
    {"chave": "triagem_propostas", "rotulo": "Pré-triagem de propostas",
     "grupo": "organizador", "tipo_padrao": "classificacao", "ordem": 60},
    {"chave": "importacao_mapeamento",
     "rotulo": "Importação assistida da programação", "grupo": "organizador",
     "tipo_padrao": "classificacao", "ordem": 70},
    {"chave": "copiloto_evento", "rotulo": "Copiloto de criação de evento",
     "grupo": "organizador", "tipo_padrao": "classificacao", "ordem": 80},
    {"chave": "briefing_operacional", "rotulo": "Briefing operacional",
     "grupo": "organizador", "tipo_padrao": "classificacao", "ordem": 90},
    {"chave": "comunicacao", "rotulo": "Comunicação (divulgação)",
     "grupo": "organizador", "tipo_padrao": "classificacao", "ordem": 100},
    {"chave": "relatorio_narrado", "rotulo": "Relatórios narrados",
     "grupo": "organizador", "tipo_padrao": "classificacao", "ordem": 110},
    {"chave": "graficos_curadoria", "rotulo": "Curadoria de gráficos",
     "grupo": "graficos", "tipo_padrao": "classificacao", "ordem": 120},
    {"chave": "graficos_nl", "rotulo": "Gráfico por descrição (NL)",
     "grupo": "graficos", "tipo_padrao": "classificacao", "ordem": 130},
    {"chave": "graficos_insights", "rotulo": "Insights dos gráficos",
     "grupo": "graficos", "tipo_padrao": "classificacao", "ordem": 140},
]


def _registro(chave):
    for item in CONTEXTOS:
        if item["chave"] == chave:
            return item
    return None


def _padrao(tipo_padrao):
    if tipo_padrao == "texto":
        return settings.IA_MODELO_TEXTO
    return settings.IA_MODELO_CLASSIFICACAO


def invalidar_cache(sender=None, **kwargs):
    """Signal: limpa o cache quando um contexto é salvo/removido no admin."""
    try:
        cache.delete(CACHE_KEY)
    except Exception:  # noqa: BLE001 - cache é otimização; nunca quebra o fluxo
        pass


def _mapa():
    """Mapa {chave: dados} dos contextos do banco, em cache (valores simples).

    O cache é só otimização: se o backend falhar (ex.: tabela ausente em teste),
    cai direto na consulta — a configuração continua correta.
    """
    from .models import ContextoIA

    try:
        dados = cache.get(CACHE_KEY)
    except Exception:  # noqa: BLE001
        dados = None
    if dados is None:
        dados = {
            linha.chave: {
                "modelo": linha.modelo,
                "ativo": linha.ativo,
                "temperatura": linha.temperatura,
                "max_tokens": linha.max_tokens,
                "tipo_padrao": linha.tipo_padrao,
                "rotulo": linha.rotulo,
            }
            for linha in ContextoIA.objects.all()
        }
        try:
            cache.set(CACHE_KEY, dados, CACHE_TTL)
        except Exception:  # noqa: BLE001
            pass
    return dados


def config(chave):
    """Resolve o contexto: modelo, ajustes e origem.

    Precedência: linha do banco (se ativa e com modelo) → padrão do ambiente.
    Devolve dict com `modelo`, `temperatura`, `max_tokens`, `ativo`, `origem`
    (`admin`|`padrao`|`desativado`), `rotulo`, `tipo_padrao`.
    """
    linha = _mapa().get(chave)
    registro = _registro(chave) or {}
    tipo_padrao = (linha or registro).get("tipo_padrao") or "classificacao"
    rotulo = (linha or registro).get("rotulo") or chave

    resultado = {
        "chave": chave,
        "rotulo": rotulo,
        "tipo_padrao": tipo_padrao,
        "temperatura": (linha or {}).get("temperatura"),
        "max_tokens": (linha or {}).get("max_tokens"),
        "modelo": _padrao(tipo_padrao),
        "ativo": True,
        "origem": "padrao",
    }
    if not linha:
        return resultado
    if not linha["ativo"]:
        resultado["ativo"] = False
        resultado["origem"] = "desativado"
        return resultado
    if linha["modelo"]:
        resultado["modelo"] = linha["modelo"]
        resultado["origem"] = "admin"
    return resultado


def modelo(chave):
    """Só o nome do modelo resolvido do contexto."""
    return config(chave)["modelo"]


class ContextoIAInativo(RuntimeError):
    """Contexto de IA desligado no admin — os chamadores caem no fallback."""


def perfil_modelo(nome):
    """Parâmetros aceitos por família de modelo.

    Modelos novos (`gpt-5*`, `o1/o3/o4*`) usam `max_completion_tokens` e
    recusam `temperature` custom; os demais usam `max_tokens` e temperature.
    """
    nome = (nome or "").strip().lower()
    if _RE_MODELO_COMPLETION.match(nome):
        return {"token_param": "max_completion_tokens", "aceita_temperature": False}
    return {"token_param": "max_tokens", "aceita_temperature": True}


def chamada_kwargs(chave, *, max_tokens=None, temperature=None):
    """Monta os kwargs de `chat.completions.create` para o contexto.

    O que o admin definir vence; o que não estiver lá usa os defaults que o
    módulo passou (`max_tokens`/`temperature` do código). O nome do parâmetro de
    limite e a aceitação de `temperature` dependem da família do modelo. Levanta
    `ContextoIAInativo` quando o contexto está desligado.
    """
    cfg = config(chave)
    if not cfg["ativo"]:
        raise ContextoIAInativo("Contexto de IA desativado: %s" % chave)

    perfil = perfil_modelo(cfg["modelo"])
    kwargs = {"model": cfg["modelo"]}
    limite = cfg["max_tokens"] or max_tokens
    if limite:
        kwargs[perfil["token_param"]] = limite
    temp = cfg["temperatura"] if cfg["temperatura"] is not None else temperature
    if temp is not None and perfil["aceita_temperature"]:
        kwargs["temperature"] = temp
    return kwargs


def modelos_openai(forcar=False):
    """Lista os modelos de chat da OpenAI (cacheada). Erro → lista vazia.

    Usada no datalist do admin. Nunca levanta: sem chave, sem rede ou com a IA
    desligada, devolve `[]` (o campo continua sendo texto livre).
    """
    if not forcar:
        try:
            cacheado = cache.get(MODELOS_CACHE_KEY)
        except Exception:  # noqa: BLE001
            cacheado = None
        if cacheado is not None:
            return cacheado

    modelos = []
    try:
        if getattr(settings, "IA_ATIVA", True) and settings.OPENAI_API_KEY:
            import openai

            cliente = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            for item in cliente.models.list().data:
                nome = getattr(item, "id", "") or ""
                if not nome or any(t in nome.lower() for t in _MODELO_NAO_CHAT):
                    continue
                modelos.append({
                    "id": nome,
                    "created": getattr(item, "created", None),
                    "owned_by": getattr(item, "owned_by", ""),
                })
            modelos.sort(key=lambda m: m["id"])
    except Exception:  # noqa: BLE001 - listagem é acessória
        modelos = []

    try:
        cache.set(MODELOS_CACHE_KEY, modelos, MODELOS_TTL)
    except Exception:  # noqa: BLE001
        pass
    return modelos


async def chamada_kwargs_async(chave, *, max_tokens=None, temperature=None):
    """Versão assíncrona de `chamada_kwargs`.

    A leitura da configuração toca o banco (direto ou via cache DB), e os
    módulos de IA são `async`: sem isto, o Django levanta
    `SynchronousOnlyOperation`. Roda a resolução numa thread.
    """
    from asgiref.sync import sync_to_async

    return await sync_to_async(chamada_kwargs)(
        chave, max_tokens=max_tokens, temperature=temperature
    )


def modelo_da_linha(linha):
    """Modelo efetivo de uma linha (exibição no admin, sem cache)."""
    if not linha.ativo:
        return "%s (contexto desativado)" % _padrao(linha.tipo_padrao)
    if not linha.modelo:
        return "%s (padrão)" % _padrao(linha.tipo_padrao)
    return linha.modelo


def sincronizar():
    """Cria/atualiza as linhas a partir de `CONTEXTOS` (idempotente).

    Não toca em `modelo`/`temperatura`/`max_tokens`/`ativo` — só nos campos que
    vêm do código (rótulo, grupo, tipo padrão, ordem).
    """
    from .models import ContextoIA

    criados = atualizados = 0
    for item in CONTEXTOS:
        _, criado = ContextoIA.objects.update_or_create(
            chave=item["chave"],
            defaults={
                "rotulo": item["rotulo"],
                "grupo": item["grupo"],
                "tipo_padrao": item["tipo_padrao"],
                "ordem": item["ordem"],
            },
        )
        criados += 1 if criado else 0
        atualizados += 0 if criado else 1
    invalidar_cache()
    return {"criados": criados, "atualizados": atualizados, "total": len(CONTEXTOS)}
