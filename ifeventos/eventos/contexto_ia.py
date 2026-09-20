"""Contexto (dossiê) que ancora os copilotos de IA no banco de dados.

Reúne catálogos e convenções reais da escola/evento para que os prompts de IA
não fiquem genéricos: tipos de atividade (com exemplos), espaços, locais
conhecidos, campos do formulário de atividade, schema de metadados e convenções
de data/turno. Nada de PII — só estrutura e conteúdo público/interno de catálogo.

É a base compartilhada da importação assistida, do copiloto de evento, da
triagem e do concierge.
"""

from django.conf import settings

from .models import Atividade, Espaco, TipoAtividade

EXEMPLOS_POR_TIPO = 2
MAX_AMOSTRAS_ATIVIDADE = 200
MAX_TITULOS_EVENTO = 200


def catalogo_tipos():
    """Tipos do catálogo com exemplos reais (títulos) quando existirem."""
    tipos = list(TipoAtividade.objects.order_by("nome"))
    if not tipos:
        return []
    exemplos = {}
    recentes = (
        Atividade.objects.filter(publicada=True, tipo__isnull=False)
        .select_related("tipo")
        .order_by("-date_created")[:MAX_AMOSTRAS_ATIVIDADE]
    )
    for atividade in recentes:
        lista = exemplos.setdefault(atividade.tipo_id, [])
        if len(lista) < EXEMPLOS_POR_TIPO:
            lista.append(atividade.titulo)
    return [
        {"id": tipo.pk, "nome": tipo.nome, "exemplos": exemplos.get(tipo.pk, [])}
        for tipo in tipos
    ]


def catalogo_espacos():
    """Espaços do catálogo da escola (nome + capacidade)."""
    return [
        {"id": espaco.pk, "nome": espaco.nome, "capacidade": espaco.capacidade}
        for espaco in Espaco.objects.order_by("nome")
    ]


def locais_conhecidos():
    """Nomes de local já usados no sistema (catálogo + atividades + apelidos)."""
    from . import propostas

    return propostas.nomes_conhecidos()


def campos_formulario_atividade():
    """Campos REAIS do formulário de atividade do site (rótulo/obrigatório/ajuda)."""
    from .forms import AtividadeForm

    form = AtividadeForm()
    return [
        {
            "chave": nome,
            "rotulo": str(campo.label or nome),
            "obrigatorio": bool(campo.required),
            "ajuda": str(getattr(campo, "help_text", "") or ""),
        }
        for nome, campo in form.fields.items()
    ]


def schema_metadados():
    """Campos de metadados configurados pela escola (para planilhas com pessoas)."""
    return [
        {
            "chave": campo.get("chave"),
            "rotulo": campo.get("rotulo", campo.get("chave")),
            "tipo": campo.get("tipo", "texto"),
        }
        for campo in (getattr(settings, "METADADOS_PARTICIPANTE", None) or [])
    ]


def convencoes():
    """Convenções do campus usadas para interpretar a planilha."""
    return {
        "turnos": {
            "manha": "08:00-12:00",
            "tarde": "13:30-17:30",
            "noite": "18:30-22:30",
        },
        "formatos_data": [
            "dd/mm/aaaa hh:mm",
            "aaaa-mm-dd hh:mm",
            "dd/mm/aaaa",
        ],
        "aliases_local": getattr(settings, "AGENDA_ALIASES_LOCAL", None) or {},
    }


def dossie_evento(evento):
    """Recorte do evento-alvo (sem PII)."""
    from . import propostas

    chamada = propostas.chamada_de(evento)
    return {
        "titulo": evento.title,
        "categoria": evento.get_categoria_display(),
        "inicio": evento.data_inicio.strftime("%d/%m/%Y"),
        "fim": evento.data_fim.strftime("%d/%m/%Y"),
        "local": evento.local or "",
        "chamada_aberta": bool(chamada and chamada.esta_aberta()),
        "atividades_existentes": list(
            evento.atividades.values_list("titulo", flat=True)[:MAX_TITULOS_EVENTO]
        ),
    }


def dossie(evento=None):
    """Dossiê completo (catálogos globais + evento-alvo, quando informado)."""
    dados = {
        "tipos": catalogo_tipos(),
        "espacos": catalogo_espacos(),
        "locais_conhecidos": locais_conhecidos(),
        "campos_formulario": campos_formulario_atividade(),
        "metadados": schema_metadados(),
        "convencoes": convencoes(),
    }
    if evento is not None and getattr(evento, "pk", None):
        dados["evento"] = dossie_evento(evento)
    return dados


def resumo_texto(dados):
    """Versão textual compacta do dossiê, pronta para entrar no prompt."""
    linhas = []

    evento = dados.get("evento")
    if evento:
        linhas.append(
            "Evento: %s | tema: %s | %s a %s | local: %s | chamada aberta: %s"
            % (evento["titulo"], evento["categoria"], evento["inicio"],
               evento["fim"], evento["local"] or "—",
               "sim" if evento["chamada_aberta"] else "não")
        )

    tipos = dados.get("tipos") or []
    linhas.append(
        "Tipos de atividade: " + (
            ", ".join("%s (id %s)" % (t["nome"], t["id"]) for t in tipos) or "(nenhum)"
        )
    )
    for tipo in tipos:
        if tipo.get("exemplos"):
            linhas.append("  exemplo de '%s': %s" % (tipo["nome"], "; ".join(tipo["exemplos"])))

    espacos = dados.get("espacos") or []
    linhas.append(
        "Espaços: " + (
            ", ".join("%s (cap. %s)" % (e["nome"], e["capacidade"]) for e in espacos)
            or "(nenhum)"
        )
    )

    locais = dados.get("locais_conhecidos") or []
    if locais:
        linhas.append("Locais conhecidos: " + ", ".join(locais[:40]))

    campos = dados.get("campos_formulario") or []
    if campos:
        linhas.append(
            "Campos do formulário de atividade: "
            + ", ".join(c["chave"] for c in campos)
        )

    convencoes_dados = dados.get("convencoes") or {}
    turnos = convencoes_dados.get("turnos") or {}
    if turnos:
        linhas.append(
            "Turnos: " + ", ".join("%s (%s)" % (k, v) for k, v in turnos.items())
        )

    return "\n".join(linhas)
