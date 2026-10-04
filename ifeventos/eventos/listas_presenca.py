"""PDFs de lista de presença (folha de assinatura) para impressão.

Diferente do export tabular de `relatorios` — que lista e-mail e status —, aqui
a folha é para levar à porta da atividade: cabeçalho com evento, atividade,
horário, local e tipo, e uma tabela **Nome + Assinatura** (coluna em branco).

Só o nome entra na folha: ela circula no papel, e e-mail/CPF não têm por que
estar nela. A folha tem três modos (`modo`):

- `simples`: só o nome, em ordem alfabética;
- `vinculo`: nome com o vínculo (`Nome (Vínculo/Curso-Turma-Ano)`), alfabético;
- `agrupada`: em cascata — vínculo (nível 1) → curso/turma/ano (nível 2) —, com
  o nome simples nas linhas (o vínculo já está no cabeçalho do grupo).
"""

import io

from django.utils import timezone

from eventos import metadados as meta

MODO_SIMPLES = "simples"
MODO_VINCULO = "vinculo"
MODO_AGRUPADA = "agrupada"
MODOS = (MODO_SIMPLES, MODO_VINCULO, MODO_AGRUPADA)
MODO_PADRAO = MODO_VINCULO


def _quando(atividade):
    """Data/hora no fuso local, legível: `10/10/2026 08:00 às 10:00`."""
    def local(valor):
        if not valor:
            return ""
        return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M")

    inicio = local(atividade.data_hora_inicio)
    fim = local(atividade.data_hora_fim)
    if not inicio:
        return ""
    return f"{inicio} às {fim}" if fim else inicio


def _inscritos(atividade):
    """Inscritos da atividade em ordem alfabética (nome do participante)."""
    return atividade.inscritos.select_related(
        "participante", "participante__metadados"
    ).order_by(
        "participante__first_name",
        "participante__last_name",
        "participante__email",
        "id",
    )


def _dados(inscricao):
    """Metadados do participante já carregados (sem nova consulta)."""
    obj = getattr(inscricao.participante, "metadados", None)
    return dict(obj.dados) if obj else {}


def _tabela(dados):
    """Tabela `# | Nome | Assinatura` com o estilo da folha (A4 retrato)."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Table, TableStyle

    # Largura fixa que soma a área útil da A4 retrato (190 mm).
    tabela = Table(dados, colWidths=[12 * mm, 118 * mm, 60 * mm], repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f9e41")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f7f8")]),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return tabela


def _tabela_assinatura(inscritos, inicio=1, com_vinculo=True):
    """Tabela de assinatura, numerando a partir de `inicio`.

    `com_vinculo=False` usa só o nome (nos modos `simples` e `agrupada`).
    """
    dados = [["#", "Nome", "Assinatura"]]
    indice = inicio - 1
    for inscricao in inscritos:
        indice += 1
        if com_vinculo:
            nome = meta.nome_com_vinculo(inscricao.participante, _dados(inscricao))
        else:
            nome = inscricao.participante.get_full_name()
        dados.append([str(indice), nome or "—", ""])
    return _tabela(dados), indice


def _story_atividade(atividade, estilos, modo=MODO_PADRAO):
    """Blocos (platypus) de UMA atividade: cabeçalho + tabela de assinatura."""
    from reportlab.platypus import Paragraph, Spacer

    elementos = [
        Paragraph(f"Lista de Presença — {atividade.evento.title}", estilos["Title"]),
        Spacer(1, 4),
        Paragraph(atividade.titulo, estilos["Heading3"]),
    ]

    local = atividade.local or atividade.evento.local
    partes = [f"<b>Data:</b> {_quando(atividade)}"]
    if local:
        partes.append(f"<b>Local:</b> {local}")
    if atividade.tipo:
        partes.append(f"<b>Tipo:</b> {atividade.tipo.nome}")
    elementos.append(Paragraph(" &nbsp;·&nbsp; ".join(partes), estilos["Normal"]))
    elementos.append(Spacer(1, 10))

    inscritos = list(_inscritos(atividade))
    if not inscritos:
        aviso = (
            "Nenhum inscrito nesta atividade."
            if atividade.exige_inscricao
            else "Atividade sem lista de inscrição (presença por crachá/QR)."
        )
        elementos.append(Paragraph(aviso, estilos["Normal"]))
        return elementos

    if modo != MODO_AGRUPADA:
        tabela, _ = _tabela_assinatura(
            inscritos, com_vinculo=(modo == MODO_VINCULO)
        )
        elementos.append(tabela)
        return elementos

    # Agrupado: vínculo (nível 1) -> curso/turma/ano (nível 2). Nome simples nas
    # linhas: o vínculo e a turma já aparecem nos cabeçalhos.
    grupos = {}
    for inscricao in inscritos:
        dados = _dados(inscricao)
        grupos.setdefault(meta.grupo_vinculo(dados), {}).setdefault(
            meta.grupo_turma(dados), []
        ).append(inscricao)

    indice = 0
    for vinculo in sorted(grupos, key=str.lower):
        elementos.append(Paragraph(vinculo, estilos["Heading3"]))
        elementos.append(Spacer(1, 2))
        for turma in sorted(grupos[vinculo], key=str.lower):
            if turma:
                elementos.append(Paragraph(turma, estilos["Heading4"]))
            tabela, indice = _tabela_assinatura(
                grupos[vinculo][turma], inicio=indice + 1, com_vinculo=False
            )
            elementos.append(tabela)
            elementos.append(Spacer(1, 8))

    return elementos


def _documento(buffer, titulo):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate

    return SimpleDocTemplate(
        buffer, pagesize=A4, title=titulo,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
    )


def pdf_lista_presenca(atividade, modo=MODO_PADRAO):
    """PDF (bytes) da folha de assinatura de UMA atividade.

    `modo` aceita `simples`, `vinculo` ou `agrupada` (ver o topo do módulo).
    """
    from reportlab.lib.styles import getSampleStyleSheet

    if modo not in MODOS:
        modo = MODO_PADRAO
    buffer = io.BytesIO()
    documento = _documento(buffer, f"Lista de presença — {atividade.titulo}")
    documento.build(_story_atividade(atividade, getSampleStyleSheet(), modo=modo))
    return buffer.getvalue()


def pdf_listas_presenca_evento(evento, modo=MODO_PADRAO):
    """PDF (bytes) com as listas das atividades PUBLICADAS — uma por página."""
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak

    if modo not in MODOS:
        modo = MODO_PADRAO
    atividades = (
        evento.atividades.filter(publicada=True)
        .select_related("tipo")
        .order_by("data_hora_inicio", "id")
    )

    estilos = getSampleStyleSheet()
    buffer = io.BytesIO()
    documento = _documento(buffer, f"Listas de presença — {evento.title}")

    story = []
    for indice, atividade in enumerate(atividades):
        if indice:
            story.append(PageBreak())
        story.extend(_story_atividade(atividade, estilos, modo=modo))
    if not story:
        from reportlab.platypus import Paragraph

        story.append(
            Paragraph("Nenhuma atividade publicada neste evento.", estilos["Normal"])
        )

    documento.build(story)
    return buffer.getvalue()
