"""Preparação somente leitura das listas de presença do organizador."""

from collections import defaultdict

from django.utils.timezone import localtime

from eventos import metadados
from eventos.models import Inscricao


ROTULOS_VAZIOS = {
    "vinculo": "Sem vínculo informado",
    "curso": "Sem curso informado",
    "turma": "Sem turma informada",
    "ano": "Sem ano informado",
}


def _valor(dados, chave):
    return str(dados.get(chave) or "").strip() or ROTULOS_VAZIOS[chave]


def registros_lista(evento, atividade_id=None, dia=None, situacao="confirmadas"):
    """Devolve inscrições normalizadas, sem alterar a base."""
    qs = Inscricao.objects.select_related(
        "participante", "participante__metadados", "atividade", "atividade__tipo"
    ).filter(atividade__evento=evento, atividade__publicada=True)
    if atividade_id:
        qs = qs.filter(atividade_id=atividade_id)
    if dia:
        qs = qs.filter(atividade__data_hora_inicio__date=dia)
    if situacao == "confirmadas":
        qs = qs.filter(confirmada=True)
    elif situacao == "sem_confirmacao":
        qs = qs.filter(confirmada=False)
    elif situacao == "certificados":
        qs = qs.filter(confirmada=True, certificado_emitido=True)
    elif situacao == "sem_certificados":
        qs = qs.filter(confirmada=True, certificado_emitido=False)

    registros = []
    for inscricao in qs.order_by("participante__first_name", "participante__last_name", "id"):
        dados_obj = getattr(inscricao.participante, "metadados", None)
        dados = dict(dados_obj.dados) if dados_obj else {}
        inicio = localtime(inscricao.atividade.data_hora_inicio)
        registros.append({
            "inscricao": inscricao,
            "participante": inscricao.participante,
            "atividade": inscricao.atividade,
            "nome": inscricao.participante.get_full_name().strip(),
            "vinculo": _valor(dados, "vinculo"),
            "curso": _valor(dados, "curso"),
            "turma": _valor(dados, "turma"),
            "ano": _valor(dados, "ano"),
            "confirmada": inscricao.confirmada,
            "certificado_emitido": inscricao.certificado_emitido,
            "dia": inicio.strftime("%d/%m/%Y"),
            "horario": inicio.strftime("%H:%M"),
        })
        registros[-1]["nome_contexto"] = nome_com_contexto(registros[-1])
    return registros


def abreviacao(valor):
    mapa = {"Primeiro ano": "1°", "Segundo ano": "2°", "Terceiro ano": "3°", "Administração": "Adm", "Informática": "Inf"}
    return mapa.get(valor, valor)


def nome_com_contexto(registro):
    nome = registro["nome"]
    if registro["vinculo"] == "Aluno":
        return f"{nome} ({abreviacao(registro['ano'])} {abreviacao(registro['curso'])}/{registro['turma']})"
    return f"{nome} ({registro['vinculo']})"
def agrupar_por_turma(registros, por_atividade=False):
    """Agrupa vínculo → curso → turma/ano, opcionalmente separando atividades."""
    arvore = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for registro in registros:
        arvore[registro["vinculo"]][registro["curso"]][
            f"{registro['turma']} — {registro['ano']}"
        ].append(registro)
    grupos = []
    for vinculo in sorted(arvore, key=str.casefold):
        cursos = []
        for curso in sorted(arvore[vinculo], key=str.casefold):
            turmas = []
            for turma_ano in sorted(arvore[vinculo][curso], key=str.casefold):
                registros_turma = arvore[vinculo][curso][turma_ano]
                if por_atividade:
                    por_nome = defaultdict(list)
                    for registro in registros_turma:
                        por_nome[registro["atividade"].titulo].append(registro)
                    atividades = []
                    for atividade in sorted(por_nome, key=str.casefold):
                        pessoas = sorted(por_nome[atividade], key=lambda r: (r["nome"].casefold(), r["inscricao"].id))
                        for ordem, pessoa in enumerate(pessoas, 1):
                            pessoa["ordem"] = ordem
                        atividades.append({"titulo": atividade, "registros": pessoas})
                    turmas.append({"titulo": turma_ano, "atividades": atividades})
                else:
                    pessoas = sorted(registros_turma, key=lambda r: (r["nome"].casefold(), r["inscricao"].id))
                    for ordem, pessoa in enumerate(pessoas, 1):
                        pessoa["ordem"] = ordem
                    turmas.append({"titulo": turma_ano, "registros": pessoas})
            cursos.append({"titulo": curso, "turmas": turmas})
        grupos.append({"titulo": vinculo, "cursos": cursos})
    return grupos


def agrupamento_pdf(registros):
    """Prepara atividade → curso/turma/ano para o PDF, sem alterar a tela HTML."""
    arvore = defaultdict(lambda: defaultdict(list))
    for registro in registros:
        titulo = f"{registro['curso']} - {registro['turma']} — {registro['ano']}"
        arvore[registro["atividade"].titulo][titulo].append(registro)
    resultado = []
    for atividade in sorted(arvore, key=str.casefold):
        grupos = []
        for titulo in sorted(arvore[atividade], key=str.casefold):
            pessoas = sorted(arvore[atividade][titulo], key=lambda r: (r["nome"].casefold(), r["inscricao"].id))
            for ordem, pessoa in enumerate(pessoas, 1):
                pessoa["ordem"] = ordem
            grupos.append({"titulo": titulo, "registros": pessoas})
        resultado.append({"titulo": atividade, "grupos": grupos})
    return resultado
def opcoes_filtros_cascata(registros, selecionados=None):
    """Monta opções dos filtros a partir dos JSONs e das regras de metadados."""
    selecionados = selecionados or {}
    configuracao = {campo["chave"]: campo for campo in metadados.campos()}
    chaves = ("vinculo", "curso", "turma", "ano")
    resultado = {}
    for chave in chaves:
        campo = configuracao.get(chave)
        candidatos = registros
        for pai in chaves[:chaves.index(chave)]:
            valor = selecionados.get(pai, "")
            if valor:
                candidatos = [registro for registro in candidatos if registro[pai] == valor]
        valores = {registro[chave] for registro in candidatos}
        if campo:
            permitidos = metadados.opcoes_do_campo(
                campo, selecionados.get(campo["depende_de"]) if campo["depende_de"] else None
            )
            valores = valores.intersection(permitidos) if permitidos else set()
            resultado[chave + "s"] = [valor for valor in permitidos if valor in valores]
        else:
            resultado[chave + "s"] = sorted(valores, key=str.casefold)
    return resultado


def dias_evento(evento):
    """Dias distintos das atividades do evento para o filtro da tela."""
    valores = evento.atividades.order_by("data_hora_inicio").values_list("data_hora_inicio", flat=True)
    vistos = {}
    for valor in valores:
        local = localtime(valor)
        vistos.setdefault(local.date(), local.strftime("%d/%m/%Y"))
    return [(data.isoformat(), rotulo) for data, rotulo in vistos.items()]


def pdf_lista_continua(evento, registros, confirmacao=False):
    """Gera uma única tabela contínua para uma atividade, sem PageBreak por grupo."""
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm, bottomMargin=10 * mm)
    styles = getSampleStyleSheet()
    linhas = [["#", "Participante", "Dia/hora", "Situação"] if confirmacao else ["#", "Participante", "Assinatura"]]
    for ordem, registro in enumerate(sorted(registros, key=lambda r: (r["nome"].casefold(), r["inscricao"].id)), 1):
        nome = registro.get("nome_contexto") or nome_com_contexto(registro)
        if confirmacao:
            linhas.append([ordem, nome, f'{registro["dia"]} {registro["horario"]}', "Confirmada" if registro["confirmada"] else "x Ausente"])
        else:
            linhas.append([ordem, nome, "________________________________"])
    story = [Paragraph(f"<b>{evento.title}</b>", styles["Normal"]), Spacer(1, 5)]
    tabela = Table(linhas, colWidths=[10 * mm, (75 if confirmacao else 90) * mm, (45 if confirmacao else 90) * mm, 60 * mm] if confirmacao else [10 * mm, 90 * mm, 90 * mm], repeatRows=1)
    tabela.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#238b45")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#cccccc")), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    story.append(tabela)
    doc.build(story)
    return buffer.getvalue()


def pdf_lista_preparada(evento, grupos, confirmacao=False):
    """Gera PDF da estrutura preparada, sem expor e-mail/CPF."""
    import io
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=10*mm, bottomMargin=10*mm)
    styles = getSampleStyleSheet()
    story = []
    informacoes_evento = (
        f"<b>{evento.title}</b> · "
        f"{evento.data_inicio.strftime('%d/%m/%Y')} a {evento.data_fim.strftime('%d/%m/%Y')}"
    )
    if evento.local:
        informacoes_evento += f" · {evento.local}"
    for atividade in grupos:
        for grupo in atividade["grupos"]:
            story.append(PageBreak() if story else Spacer(1, 0))
            story.append(Paragraph(informacoes_evento, styles["Normal"]))
            story.append(Paragraph(f"Atividade: {atividade['titulo']}", styles["Heading2"]))
            story.append(Paragraph(grupo["titulo"], styles["Heading3"]))
            cab = ["#", "Participante", "Dia/hora", "Situação"] if confirmacao else ["#", "Participante", "Assinatura"]
            linhas = [cab]
            for r in grupo["registros"]:
                if confirmacao:
                    linhas.append([r["ordem"], r["nome"], f'{r["dia"]} {r["horario"]}', "Confirmada" if r["confirmada"] else "x Ausente"])
                else:
                    linhas.append([r["ordem"], r["nome"], "________________________________"])
            larguras_mm = [10, 75, 45, 60] if confirmacao else [10, 90, 90]
            tabela = Table(linhas, colWidths=[largura * mm for largura in larguras_mm], repeatRows=1)
            tabela.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#238b45")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#cccccc")),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7f5")]),
            ]))
            story.extend([tabela, Spacer(1, 8)])
    doc.build(story)
    return buffer.getvalue()
