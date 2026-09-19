"""Agregações por pessoa/grupo dos relatórios (regra única dos números).

Diferente de `graficos.py` (que agrega o evento para os gráficos), aqui o eixo é
a **pessoa**: o que cada uma fez no evento (inscrições, presenças, carga
horária, certificados, papéis) e, por cima disso, o resumo por **grupo**
(turma/curso/ano…).

Tudo é calculado em Python a partir de poucas consultas (nunca uma por pessoa),
para os relatórios do organizador e a área do participante contarem a MESMA
história. Funções puras: recebem o evento e devolvem dados — sem request.
"""

from collections import Counter, defaultdict

from django.utils import timezone

from eventos import crachas
from eventos.models import Certificado, Inscricao, Participante, Presenca, PresencaCancelada
from eventos.metadados import campos as campos_metadados


def _metadados(participante):
    obj = getattr(participante, "metadados", None)
    return dict(obj.dados) if obj else {}


def carga_horaria(presencas):
    """Soma a duração das atividades com presença registrada (em horas).

    Usa a duração real de cada atividade (fim − início). Não há presença
    parcial no modelo: quem tem presença conta a atividade inteira.
    """
    total = 0.0
    for presenca in presencas:
        atividade = presenca.atividade
        if not atividade or not atividade.data_hora_inicio or not atividade.data_hora_fim:
            continue
        total += (atividade.data_hora_fim - atividade.data_hora_inicio).total_seconds()
    return round(total / 3600, 1)


def _filtro_metadados(participantes, termo):
    """Filtra em memória por nome/e-mail/matrícula/curso/turma (busca do relatório)."""
    if not termo:
        return participantes
    palavras = [p for p in termo.lower().split() if p]
    chaves = [c["chave"] for c in campos_metadados()]
    resultado = []
    for pessoa in participantes:
        dados = _metadados(pessoa)
        texto = " ".join([
            pessoa.first_name or "", pessoa.last_name or "", pessoa.email or "",
            *[str(dados.get(c, "")) for c in chaves],
        ]).lower()
        if all(palavra in texto for palavra in palavras):
            resultado.append(pessoa)
    return resultado


def resumo_por_pessoa(evento, termo="", presenca=None, certificado=None):
    """Uma linha por pessoa com papel no evento.

    Devolve uma lista de dicts com contagens, carga horária, papéis e os campos
    de metadados. `termo` filtra por nome/e-mail/metadados; `presenca` aceita
    "com"/"sem" e `certificado` "sim"/"nao" (filtros da tela).
    """
    ids = set()
    if evento.organizador_id:
        ids.add(evento.organizador_id)
    ids.update(evento.atividades.values_list("palestrantes__id", flat=True))
    ids.update(
        Inscricao.objects.filter(atividade__evento=evento).values_list(
            "participante_id", flat=True
        )
    )
    ids.discard(None)

    pessoas = list(
        Participante.objects.filter(id__in=ids)
        .select_related("metadados")
        .order_by("first_name", "last_name", "id")
    )
    pessoas = _filtro_metadados(pessoas, termo)

    # Três consultas fixas, agrupadas por pessoa (sem N+1).
    inscricoes = defaultdict(int)
    for pessoa_id in Inscricao.objects.filter(
        atividade__evento=evento
    ).values_list("participante_id", flat=True):
        inscricoes[pessoa_id] += 1

    presencas_por_pessoa = defaultdict(list)
    for presenca_obj in Presenca.objects.filter(
        atividade__evento=evento
    ).select_related("atividade"):
        presencas_por_pessoa[presenca_obj.participante_id].append(presenca_obj)

    certificados = defaultdict(int)
    for pessoa_id in Certificado.objects.filter(
        atividade__evento=evento
    ).values_list("participante_id", flat=True):
        certificados[pessoa_id] += 1

    canceladas = defaultdict(int)
    for pessoa_id in PresencaCancelada.objects.filter(
        atividade__evento=evento
    ).values_list("participante_id", flat=True):
        canceladas[pessoa_id] += 1

    linhas = []
    for pessoa in pessoas:
        presencas = presencas_por_pessoa.get(pessoa.id, [])
        n_inscricoes = inscricoes.get(pessoa.id, 0)
        n_presencas = len(presencas)
        n_certificados = certificados.get(pessoa.id, 0)

        if presenca == "com" and n_presencas == 0:
            continue
        if presenca == "sem" and n_presencas > 0:
            continue
        if certificado == "sim" and n_certificados == 0:
            continue
        if certificado == "nao" and n_certificados > 0:
            continue

        linhas.append({
            "pessoa": pessoa,
            "metadados": _metadados(pessoa),
            "papeis": crachas.papeis_no_evento(pessoa, evento),
            "n_inscricoes": n_inscricoes,
            "n_presencas": n_presencas,
            "n_certificados": n_certificados,
            "carga_horaria": carga_horaria(presencas),
            "taxa_presenca": round(100 * n_presencas / n_inscricoes) if n_inscricoes else 0,
            "taxa_certificacao": round(100 * n_certificados / n_presencas) if n_presencas else 0,
            "presencas_canceladas": canceladas.get(pessoa.id, 0),
        })
    return linhas


def atividades_da_pessoa(evento, pessoa):
    """Atividades do evento com o que a pessoa fez em cada uma (detalhe do aluno)."""
    inscricoes = {
        i.atividade_id: i
        for i in Inscricao.objects.filter(
            atividade__evento=evento, participante=pessoa
        ).select_related("atividade")
    }
    presencas = {
        p.atividade_id: p
        for p in Presenca.objects.filter(
            atividade__evento=evento, participante=pessoa
        ).select_related("atividade")
    }
    certificados = {
        c.atividade_id
        for c in Certificado.objects.filter(
            atividade__evento=evento, participante=pessoa
        )
        if c.atividade_id
    }
    return {
        "inscricoes": inscricoes,
        "presencas": presencas,
        "certificados": certificados,
    }


def grupo_de(linha, agrupar="curso_turma_ano"):
    """Rótulo do grupo de uma linha (mesma regra de `resumo_por_grupo`)."""
    chaves = agrupar.split("_") if agrupar else []
    partes = [str(linha["metadados"].get(chave, "") or "").strip() for chave in chaves]
    partes = [p for p in partes if p]
    return " · ".join(partes) if partes else "(sem grupo)"


def resumo_por_grupo(linhas, agrupar="curso_turma_ano"):
    """Agrupa as linhas de `resumo_por_pessoa` por metadado.

    `agrupar` aceita uma chave de metadado (ex.: `turma`, `curso`) ou a
    composição `curso_turma_ano`. A soma dos grupos bate com os totais das
    linhas (teste de invariante): cada pessoa entra em exatamente um grupo.
    """
    chaves = agrupar.split("_") if agrupar else []

    def rotulo(linha):
        partes = [str(linha["metadados"].get(chave, "") or "").strip() for chave in chaves]
        partes = [p for p in partes if p]
        return " · ".join(partes) if partes else "(sem grupo)"

    grupos = {}
    for linha in linhas:
        nome = rotulo(linha)
        grupo = grupos.setdefault(nome, {
            "grupo": nome, "pessoas": 0, "inscricoes": 0, "presencas": 0,
            "certificados": 0, "carga_horaria": 0.0,
        })
        grupo["pessoas"] += 1
        grupo["inscricoes"] += linha["n_inscricoes"]
        grupo["presencas"] += linha["n_presencas"]
        grupo["certificados"] += linha["n_certificados"]
        grupo["carga_horaria"] = round(grupo["carga_horaria"] + linha["carga_horaria"], 1)

    resultado = []
    for grupo in grupos.values():
        grupo["taxa_presenca"] = (
            round(100 * grupo["presencas"] / grupo["inscricoes"]) if grupo["inscricoes"] else 0
        )
        grupo["taxa_certificacao"] = (
            round(100 * grupo["certificados"] / grupo["presencas"]) if grupo["presencas"] else 0
        )
        resultado.append(grupo)
    return sorted(resultado, key=lambda g: g["grupo"].lower())


def graficos_grupos(grupos):
    """Gráficos prontos (contrato do Chart.js) a partir das linhas por grupo."""
    graficos = []
    if not grupos:
        return graficos

    graficos.append({
        "id": "grupos_pessoas",
        "titulo": "Participantes por grupo",
        "tipo": "bar",
        "labels": [g["grupo"] for g in grupos],
        "series": [{"nome": "Pessoas", "data": [g["pessoas"] for g in grupos], "cor": "indigo"}],
    })
    if any(g["presencas"] for g in grupos):
        graficos.append({
            "id": "grupos_presenca",
            "titulo": "Taxa de presença por grupo",
            "tipo": "bar",
            "labels": [g["grupo"] for g in grupos],
            "series": [{"nome": "Presença (%)", "data": [g["taxa_presenca"] for g in grupos], "cor": "verde"}],
        })
    if any(g["certificados"] for g in grupos):
        graficos.append({
            "id": "grupos_certificacao",
            "titulo": "Taxa de certificação por grupo",
            "tipo": "bar",
            "labels": [g["grupo"] for g in grupos],
            "series": [{"nome": "Certificação (%)", "data": [g["taxa_certificacao"] for g in grupos], "cor": "ambar"}],
        })
    return graficos


def graficos_alunos(linhas):
    """Gráficos prontos (contrato do Chart.js) a partir das linhas por pessoa."""
    from collections import Counter

    def contagem(campo, titulo, tipo="donut", limite=12):
        valores = Counter(
            str(linha["metadados"].get(campo, "") or "—") for linha in linhas
        )
        itens = valores.most_common(limite)
        return {
            "id": "alunos_%s" % campo,
            "titulo": titulo,
            "tipo": tipo,
            "labels": [nome for nome, _ in itens],
            "series": [{"nome": titulo, "data": [n for _, n in itens], "cor": "paleta"}],
        }

    # Vínculo/curso só entram se houver dado (senão o gráfico fica vazio).
    graficos = []
    for campo, titulo in (("vinculo", "Participantes por vínculo"),
                          ("curso", "Participantes por curso"),
                          ("turma", "Participantes por turma")):
        if any(str(linha["metadados"].get(campo, "")).strip() for linha in linhas):
            graficos.append(contagem(campo, titulo))

    top = sorted(linhas, key=lambda l: (-l["carga_horaria"], l["pessoa"].first_name or ""))[:10]
    if any(linha["carga_horaria"] for linha in top):
        graficos.append({
            "id": "alunos_carga",
            "titulo": "Carga horária por participante (top 10)",
            "tipo": "barh",
            "labels": [
                (f"{l['pessoa'].first_name} {l['pessoa'].last_name}").strip()
                for l in top
            ],
            "series": [{"nome": "Horas", "data": [l["carga_horaria"] for l in top], "cor": "verde"}],
        })

    presentes = sum(linha["n_presencas"] for linha in linhas)
    ausentes = sum(max(linha["n_inscricoes"] - linha["n_presencas"], 0) for linha in linhas)
    if presentes or ausentes:
        graficos.append({
            "id": "alunos_presenca",
            "titulo": "Presenças × ausências",
            "tipo": "donut",
            "labels": ["Presentes", "Ausentes"],
            "series": [{"nome": "Marcações", "data": [presentes, ausentes], "cor": "paleta"}],
        })
    return graficos


def resumo_por_atividade(evento, tipo_id=None):
    """Linhas por atividade: inscritos, presentes, vagas e ocupação.

    `tipo_id` opcional filtra por tipo de atividade; com ele os KPIs usam só
    esse recorte. Ordena por data/hora (grade).
    """
    from eventos.models import Presenca

    atividades = list(
        evento.atividades.select_related("tipo").order_by("data_hora_inicio", "titulo")
    )
    if tipo_id:
        atividades = [a for a in atividades if a.tipo_id == tipo_id]

    presentes_por_atividade = Counter(
        Presenca.objects.filter(atividade__evento=evento).values_list("atividade_id", flat=True)
    )
    linhas = []
    for atividade in atividades:
        inscritos = atividade.n_inscricoes or 0
        vagas = atividade.n_vagas or 0
        presentes = presentes_por_atividade.get(atividade.id, 0)
        ocupacao = round(100 * inscritos / vagas) if vagas else 0
        linhas.append({
            "atividade": atividade,
            "tipo": atividade.tipo.nome if atividade.tipo_id else "Sem tipo",
            "inscritos": inscritos,
            "presentes": presentes,
            "vagas": vagas,
            "ocupacao": ocupacao,
            "emite_certificado": atividade.emite_certificado,
        })
    return linhas


def kpis_atividades(linhas):
    """Indicadores do topo do relatório por tipo de atividade."""
    atividades = len(linhas)
    inscritos = sum(linha["inscritos"] for linha in linhas)
    vagas = sum(linha["vagas"] for linha in linhas)
    presentes = sum(linha["presentes"] for linha in linhas)
    tipos = len({linha["tipo"] for linha in linhas})
    return [
        {"rotulo": "Atividades", "valor": atividades, "icone": "fa-solid fa-calendar-days"},
        {"rotulo": "Inscrições", "valor": inscritos, "icone": "fa-solid fa-clipboard-list"},
        {"rotulo": "Vagas", "valor": vagas, "icone": "fa-solid fa-door-open"},
        {"rotulo": "Presentes", "valor": presentes, "icone": "fa-solid fa-clipboard-check"},
        {"rotulo": "Tipos", "valor": tipos, "icone": "fa-solid fa-tags"},
    ]


def graficos_atividades(linhas):
    """Gráficos prontos (contrato do Chart.js) a partir das linhas por atividade."""
    graficos = []
    if not linhas:
        return graficos

    top = sorted(linhas, key=lambda l: (-l["inscritos"], l["atividade"].titulo or ""))[:10]
    graficos.append({
        "id": "atividades_ocupacao",
        "titulo": "Inscritos × vagas por atividade (top 10)",
        "tipo": "barh",
        "labels": [l["atividade"].titulo for l in top],
        "series": [
            {"nome": "Inscritos", "data": [l["inscritos"] for l in top], "cor": "indigo"},
            {"nome": "Vagas", "data": [l["vagas"] for l in top], "cor": "cinza"},
        ],
    })
    if any(l["presentes"] for l in linhas):
        top_presenca = sorted(linhas, key=lambda l: (-l["presentes"], l["atividade"].titulo or ""))[:10]
        graficos.append({
            "id": "atividades_comparecimento",
            "titulo": "Comparecimento por atividade (top 10)",
            "tipo": "bar",
            "labels": [l["atividade"].titulo for l in top_presenca],
            "series": [
                {"nome": "Presentes", "data": [l["presentes"] for l in top_presenca], "cor": "verde"},
                {"nome": "Ausentes",
                 "data": [max(l["inscritos"] - l["presentes"], 0) for l in top_presenca],
                 "cor": "vermelho"},
            ],
        })
    return graficos


def kpis_alunos(linhas):
    """Indicadores do topo do relatório por aluno."""
    pessoas = len(linhas)
    presencas = sum(linha["n_presencas"] for linha in linhas)
    inscricoes = sum(linha["n_inscricoes"] for linha in linhas)
    certificados = sum(linha["n_certificados"] for linha in linhas)
    horas = round(sum(linha["carga_horaria"] for linha in linhas), 1)
    return [
        {"rotulo": "Pessoas", "valor": pessoas, "icone": "fa-solid fa-users"},
        {"rotulo": "Inscrições", "valor": inscricoes, "icone": "fa-solid fa-clipboard-list"},
        {"rotulo": "Presenças", "valor": presencas, "icone": "fa-solid fa-clipboard-check"},
        {"rotulo": "Certificados", "valor": certificados, "icone": "fa-solid fa-certificate"},
        {"rotulo": "Carga horária total", "valor": horas, "sufixo": "h", "icone": "fa-regular fa-clock"},
    ]
