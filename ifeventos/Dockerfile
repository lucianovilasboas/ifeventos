FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /ifeventos

COPY . .

RUN chmod +x entrypoint.sh

RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt


# CMD ["python", "manage.py", "runserver", "0.0.0.0:8501"]
ENTRYPOINT ["./entrypoint.sh"]
