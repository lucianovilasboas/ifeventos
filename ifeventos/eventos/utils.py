# from reportlab.lib.pagesizes import landscape, A4
# from reportlab.pdfgen import canvas
# from django.core.files.base import ContentFile
# import io

# def gerar_certificado(participante, atividade=None, evento=None):
#     """
#     Gera um certificado em PDF para um participante.
#     """
#     buffer = io.BytesIO()
#     c = canvas.Canvas(buffer, pagesize=landscape(A4))
    
#     c.setFont("Helvetica-Bold", 24)
#     c.drawString(250, 500, "Certificado de Participação")
    
#     c.setFont("Helvetica", 18)
#     c.drawString(250, 450, f"Certificamos que {participante.first_name} {participante.last_name}")
    
#     if atividade:
#         c.drawString(250, 400, f"Participou da atividade '{atividade.titulo}'.")
#     elif evento:
#         c.drawString(250, 400, f"Participou do evento '{evento.title}'.")
    
#     c.setFont("Helvetica", 14)
#     c.drawString(250, 350, "Data de emissão: XX/XX/XXXX")
    
#     c.showPage()
#     c.save()

#     pdf_file = ContentFile(buffer.getvalue(), f"certificado_{participante.id}.pdf")
#     return pdf_file



from reportlab.lib.pagesizes import landscape, A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor
from django.conf import settings
from django.core.files.base import ContentFile
import qrcode
import io

def gerar_certificado(participante, atividade=None, evento=None):
    """
    Gera um certificado em PDF mais elaborado, incluindo:
    - Logo (centralizada no topo, com redimensionamento proporcional)
    - Título e demais textos deslocados para evitar sobreposição
    - QR Code de autenticação
    - Bordas e assinatura do organizador
    """
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))

    # Dimensões da página
    width, height = landscape(A4)

    # Cores
    primary_color = HexColor("#2E86C1")  # Azul forte
    text_color = HexColor("#1C2833")      # Preto escuro
    line_color = HexColor("#2980B9")      # Azul claro

    # Fundo
    c.setFillColor(HexColor("#F0F3F4"))
    c.rect(0, 0, width, height, fill=True, stroke=False)

    # Bordas
    c.setStrokeColor(line_color)
    c.setLineWidth(5)
    c.rect(20, 20, width - 40, height - 40)

    # Adicionando Logo do Evento (Centralizada no Topo)
    try:
        logo_path = "media/logo_ifmg.png"  # Atualize com o caminho real da sua logo
        logo = ImageReader(logo_path)

        # Obtém o tamanho real da imagem
        logo_width, logo_height = logo.getSize()

        # Define o tamanho máximo permitido para a logo
        max_logo_width = 300
        max_logo_height = 150

        # Redimensiona proporcionalmente se necessário
        if logo_width > max_logo_width or logo_height > max_logo_height:
            aspect_ratio = logo_width / logo_height
            if logo_width > logo_height:
                logo_width = max_logo_width
                logo_height = max_logo_width / aspect_ratio
            else:
                logo_height = max_logo_height
                logo_width = max_logo_height * aspect_ratio

        # Centraliza a logo no topo (deixando uma margem de 50 do topo)
        x_logo = (width - logo_width) / 2
        y_logo = height - logo_height - 50

        c.drawImage(logo, x_logo, y_logo, width=logo_width, height=logo_height, mask='auto')

        # Define a posição do título abaixo da logo
        titulo_y = y_logo - 40
    except Exception as e:
        print(f"Erro ao carregar a logo do evento: {e}")
        titulo_y = height - 100

    # Título do certificado
    c.setFont("Helvetica-Bold", 36)
    c.setFillColor(primary_color)
    c.drawCentredString(width / 2, titulo_y, "CERTIFICADO DE PARTICIPAÇÃO")

    # Texto "Certificamos que"
    texto_base_y = titulo_y - 60
    c.setFont("Helvetica-Bold", 24)
    c.setFillColor(text_color)
    c.drawCentredString(width / 2, texto_base_y, "Certificamos que")

    # Nome do participante
    c.setFont("Helvetica-Bold", 28)
    c.setFillColor(HexColor("#D35400"))  # Destaque em laranja
    c.drawCentredString(width / 2, texto_base_y - 40, f"{participante.get_full_name()}")

    # Informações da participação (atividade ou evento)
    info_y = texto_base_y - 100
    c.setFont("Helvetica", 20)
    c.setFillColor(text_color)
    if atividade:
        c.drawCentredString(width / 2, info_y, "Participou da atividade:")
        c.setFont("Helvetica-Bold", 22)
        c.drawCentredString(width / 2, info_y - 40, f"'{atividade.titulo}'")
    elif evento:
        c.drawCentredString(width / 2, info_y, "Participou do evento:")
        c.setFont("Helvetica-Bold", 22)
        c.drawCentredString(width / 2, info_y - 40, f"'{evento.title}'")

    # Data de emissão
    date_y = info_y - 80
    c.setFont("Helvetica", 16)
    if evento:
        date_str = evento.data_fim.strftime('%d/%m/%Y')
    else:
        date_str = "XX/XX/XXXX"
    c.drawCentredString(width / 2, date_y, f"Emitido em: {date_str}")

    # QR Code (Autenticação)
    # A URL vem do ambiente (SITE_URL). Antes era um domínio DuckDNS fixo
    # com a porta 8502 de outro serviço, que não existe neste projeto.
    # O QR aponta para a rota pública /c/<token>/. Antes era montado aqui
    # `{SITE_URL}/verificar-certificado/<id>`, endereço que não existe em
    # nenhum urls.py — todo certificado impresso levava a um 404.
    from .crachas import gerar_token, url_verificacao

    qr_data = url_verificacao(
        gerar_token(
            participante.id,
            evento_id=getattr(evento, "id", None),
            tipo="certificado",
            atividade_id=getattr(atividade, "id", None),
        )
    )
    qr = qrcode.make(qr_data)
    qr_buffer = io.BytesIO()
    qr.save(qr_buffer, format="PNG")
    qr_img = ImageReader(qr_buffer)
    c.drawImage(qr_img, width - 160, 50, width=100, height=100, mask='auto')

    # Espaço para Assinatura do Organizador
    c.line(100, 50, 350, 50)  # Linha para assinatura
    c.setFont("Helvetica", 14)
    organizador_nome = evento.organizador.get_full_name() if evento else "Nome do Organizador"
    c.drawCentredString(225, 30, organizador_nome)

    c.showPage()
    c.save()

    pdf_file = ContentFile(buffer.getvalue(), f"certificado_{participante.id}.pdf")
    return pdf_file