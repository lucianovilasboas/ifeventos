FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /ifeventos

COPY . .

RUN chmod +x entrypoint.sh

# LibreOffice (headless) + fontes: converte os certificados no modo .docx para
# PDF. Sem isto, só o modo "fundo" (reportlab) funciona. Aumenta a imagem.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-liberation \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt


# CMD ["python", "manage.py", "runserver", "0.0.0.0:8501"]
ENTRYPOINT ["./entrypoint.sh"]
