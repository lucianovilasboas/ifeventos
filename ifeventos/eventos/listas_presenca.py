"""PDFs de lista de presença (folha de assinatura) para impressão.

Diferente do export tabular de `relatorios` — que lista e-mail e status —, aqui
a folha é para levar à porta da atividade: cabeçalho com evento, atividade,
horário, local e tipo, e uma tabela **Nome + Assinatura** (coluna em branco).

Só o nome entra na folha: ela circula no papel, e e-mail/CPF não têm por que
estar nela.
"""

import io

from django.utils import timezone


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
    return atividade.inscritos.select_related("participante").order_by(
        "participante__first_name",
        "participante__last_name",
        "participante__email",
        "id",
    )


def _story_atividade(atividade, estilos):
    """Blocos (platypus) de UMA atividade: cabeçalho + tabela de assinatura."""
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

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
    if inscritos:
        dados = [["#", "Nome", "Assinatura"]]
        for indice, inscricao in enumerate(inscritos, start=1):
            nome = inscricao.participante.get_full_name() or "—"
            dados.append([str(indice), nome, ""])

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
        elementos.append(tabela)
    else:
        aviso = (
            "Nenhum inscrito nesta atividade."
            if atividade.exige_inscricao
            else "Atividade sem lista de inscrição (presença por crachá/QR)."
        )
        elementos.append(Paragraph(aviso, estilos["Normal"]))

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


def pdf_lista_presenca(atividade):
    """PDF (bytes) da folha de assinatura de UMA atividade."""
    from reportlab.lib.styles import getSampleStyleSheet

    buffer = io.BytesIO()
    documento = _documento(buffer, f"Lista de presença — {atividade.titulo}")
    documento.build(_story_atividade(atividade, getSampleStyleSheet()))
    return buffer.getvalue()


def pdf_listas_presenca_evento(evento):
    """PDF (bytes) com as listas das atividades PUBLICADAS — uma por página."""
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak

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
        story.extend(_story_atividade(atividade, estilos))
    if not story:
        from reportlab.platypus import Paragraph

        story.append(
            Paragraph("Nenhuma atividade publicada neste evento.", estilos["Normal"])
        )

    documento.build(story)
    return buffer.getvalue()
