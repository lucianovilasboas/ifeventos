"""Agregações do painel analítico do organizador (gráficos por evento).

Tudo é calculado em Python e devolvido pronto para o Chart.js (via
`json_script`), sem consultas por gráfico. As funções são puras (recebem o
evento e devolvem dicionários) para poderem ser testadas sem HTTP.
"""

from collections import Counter, defaultdict

from django.utils import timezone

from eventos.models import Certificado, Inscricao, Presenca


def kpis(evento):
    """Indicadores do topo do painel."""
    from eventos.agenda import choques

    atividades = list(evento.atividades.all())
    vagas = sum(a.n_vagas or 0 for a in atividades)
    inscritos = sum(a.n_inscricoes or 0 for a in atividades)
    inscricoes = Inscricao.objects.filter(atividade__evento=evento).count()
    presencas = Presenca.objects.filter(atividade__evento=evento).count()
    certificados = Certificado.objects.filter(atividade__evento=evento).count()
    publicadas = sum(1 for a in atividades if a.publicada)

    return [
        {"rotulo": "Inscrições", "valor": inscricoes, "icone": "fa-solid fa-users"},
        {"rotulo": "Atividades", "valor": len(atividades), "icone": "fa-solid fa-list-check"},
        {"rotulo": "Vagas oferecidas", "valor": vagas, "icone": "fa-solid fa-chair"},
        {
            "rotulo": "Ocupação média",
            "valor": round(100 * inscritos / vagas) if vagas else 0,
            "sufixo": "%",
            "icone": "fa-solid fa-gauge-high",
        },
        {
            "rotulo": "Comparecimento",
            "valor": round(100 * presencas / inscricoes) if inscricoes else 0,
            "sufixo": "%",
            "icone": "fa-solid fa-clipboard-check",
        },
        {"rotulo": "Certificados", "valor": certificados, "icone": "fa-solid fa-certificate"},
        {"rotulo": "Rascunhos", "valor": len(atividades) - publicadas, "icone": "fa-solid fa-eye-slash"},
        {"rotulo": "Conflitos na grade", "valor": len(choques(atividades)), "icone": "fa-solid fa-triangle-exclamation"},
    ]


def graficos(evento):
    """Lista de gráficos prontos para o Chart.js."""
    from eventos.agenda import locais_de

    atividades = list(
        evento.atividades.select_related("tipo").prefetch_related("palestrantes")
    )
    return [
        _ocupacao_por_atividade(atividades),
        _inscricoes_por_tipo(atividades),
        _ocupacao_por_sala(atividades, locais_de),
        _evolucao_inscricoes(evento),
        _comparecimento_por_atividade(evento, atividades),
        _vagas_ociosas(atividades),
        *_perfil_inscritos(evento),
        _publicacao(atividades),
    ]


def _ocupacao_por_atividade(atividades, limite=10):
    """As atividades mais procuradas (inscritos × vagas)."""
    top = sorted(atividades, key=lambda a: (-(a.n_inscricoes or 0), a.titulo))[:limite]
    return {
        "id": "ocupacao_atividade",
        "titulo": "Ocupação por atividade",
        "tipo": "barh",
        "labels": [a.titulo for a in top],
        "series": [
            {"nome": "Inscritos", "data": [a.n_inscricoes or 0 for a in top], "cor": "indigo"},
            {"nome": "Vagas", "data": [a.n_vagas or 0 for a in top], "cor": "cinza"},
        ],
    }


def _inscricoes_por_tipo(atividades):
    contagem = Counter(
        (a.tipo.nome if a.tipo_id else "Sem tipo") for a in atividades
        for _ in range(a.n_inscricoes or 0)
    )
    return {
        "id": "inscricoes_por_tipo",
        "titulo": "Inscrições por tipo de atividade",
        "tipo": "donut",
        "labels": list(contagem),
        "series": [{"nome": "Inscrições", "data": list(contagem.values()), "cor": "paleta"}],
    }


def _ocupacao_por_sala(atividades, locais_de, limite=10):
    salas = defaultdict(lambda: {"vagas": 0, "inscritos": 0})
    for atividade in atividades:
        for local in locais_de(atividade) or ["Sem local definido"]:
            salas[local]["vagas"] += atividade.n_vagas or 0
            salas[local]["inscritos"] += atividade.n_inscricoes or 0
    ordenadas = sorted(
        salas.items(),
        key=lambda item: (-(item[1]["inscritos"]), item[0].lower()),
    )[:limite]
    return {
        "id": "ocupacao_sala",
        "titulo": "Ocupação por sala",
        "tipo": "barh",
        "labels": [nome for nome, _ in ordenadas],
        "series": [
            {"nome": "Inscritos", "data": [d["inscritos"] for _, d in ordenadas], "cor": "verde"},
            {"nome": "Vagas", "data": [d["vagas"] for _, d in ordenadas], "cor": "cinza"},
        ],
    }


def _evolucao_inscricoes(evento):
    """Inscrições por dia (data de criação) — velocidade de adesão."""
    contagem = Counter(
        timezone.localtime(criada).date()
        for criada in Inscricao.objects.filter(atividade__evento=evento)
        .values_list("created_at", flat=True)
    )
    dias = sorted(contagem)
    return {
        "id": "evolucao",
        "titulo": "Evolução das inscrições",
        "tipo": "line",
        "labels": [dia.strftime("%d/%m") for dia in dias],
        "series": [{"nome": "Inscrições no dia", "data": [contagem[d] for d in dias], "cor": "verde"}],
    }


def _comparecimento_por_atividade(evento, atividades, limite=10):
    presentes = Counter(
        Presenca.objects.filter(atividade__evento=evento).values_list("atividade_id", flat=True)
    )
    top = sorted(atividades, key=lambda a: (-(a.n_inscricoes or 0), a.titulo))[:limite]
    ausentes = [max((a.n_inscricoes or 0) - presentes.get(a.id, 0), 0) for a in top]
    return {
        "id": "comparecimento",
        "titulo": "Comparecimento por atividade (top 10 procuradas)",
        "tipo": "bar",
        "labels": [a.titulo for a in top],
        "series": [
            {"nome": "Presentes", "data": [presentes.get(a.id, 0) for a in top], "cor": "verde"},
            {"nome": "Não compareceram", "data": ausentes, "cor": "vermelho"},
        ],
    }


def _vagas_ociosas(atividades, limite=10):
    ociosas = sorted(
        [a for a in atividades if (a.n_vagas or 0) > (a.n_inscricoes or 0)],
        key=lambda a: -((a.n_vagas or 0) - (a.n_inscricoes or 0)),
    )[:limite]
    return {
        "id": "vagas_ociosas",
        "titulo": "Vagas ociosas (top 10)",
        "tipo": "barh",
        "labels": [a.titulo for a in ociosas],
        "series": [
            {"nome": "Vagas livres",
             "data": [(a.n_vagas or 0) - (a.n_inscricoes or 0) for a in ociosas],
             "cor": "ambar"},
        ],
    }


def _perfil_inscritos(evento):
    """Inscrições por campo de metadado (vínculo/curso/turma…), se preenchido.

    O schema de metadados é configurável por escola; só os campos de escolha com
    algum valor preenchido viram gráfico.
    """
    from eventos.metadados import campos

    inscritos = list(
        Inscricao.objects.filter(atividade__evento=evento)
        .select_related("participante__metadados")
        .values_list("participante__metadados__dados", flat=True)
    )
    graficos = []
    for campo in campos():
        if campo["tipo"] != "escolha" or campo["depende_de"]:
            continue
        contagem = Counter(
            (dados or {}).get(campo["chave"], "")
            for dados in inscritos
        )
        contagem.pop("", None)
        if not contagem:
            continue
        graficos.append({
            "id": f"perfil_{campo['chave']}",
            "titulo": f"Inscrições por {campo['rotulo'].lower()}",
            "tipo": "donut",
            "labels": list(contagem),
            "series": [{"nome": campo["rotulo"], "data": list(contagem.values()), "cor": "paleta"}],
        })
        if len(graficos) >= 3:
            break
    return graficos


def _publicacao(atividades):
    publicadas = sum(1 for a in atividades if a.publicada)
    return {
        "id": "publicacao",
        "titulo": "Publicadas × rascunhos",
        "tipo": "donut",
        "labels": ["Publicadas", "Rascunhos"],
        "series": [{"nome": "Atividades", "data": [publicadas, len(atividades) - publicadas], "cor": "paleta"}],
    }


def heatmap(evento):
    """Matriz dia × hora com o nº de atividades que começam no horário."""
    atividades = evento.atividades.values_list("data_hora_inicio", flat=True)
    dias, horas, matriz = [], set(), Counter()
    for inicio in atividades:
        local = timezone.localtime(inicio)
        if local.date() not in dias:
            dias.append(local.date())
        horas.add(local.hour)
        matriz[(local.date(), local.hour)] += 1
    horas = sorted(horas)
    return {
        "dias": dias,
        "horas": horas,
        "linhas": [
            {"rotulo": f"{hora:02d}:00", "celulas": [matriz.get((dia, hora), 0) for dia in dias]}
            for hora in horas
        ],
        "maximo": max(matriz.values()) if matriz else 0,
    }
