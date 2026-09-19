"""Importação da programação (atividades) por arquivo — CSV/XLS/XLSX.

Um arquivo por evento: cada linha vira uma `Atividade`. Colunas (cabeçalho):
`titulo, descricao, tipo, local, inicio, fim, n_vagas, emite_certificado,
palestrantes`.

Regras:
  - a chave de idempotência é **título + início** (rodar de novo ATUALIZA);
  - `tipo` precisa existir (a linha vira erro — não criamos tipos sozinhos);
  - `inicio`/`fim` aceitam ISO (`2026-10-05 08:00`) ou `05/10/2026 08:00`;
  - `palestrantes` são e-mails separados por `;`/`,`; sem conta, avisa e ignora;
  - `emite_certificado` aceita sim/não/true/1.
"""

from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Atividade, Participante, TipoAtividade

COLUNAS = (
    "titulo", "descricao", "tipo", "local",
    "inicio", "fim", "n_vagas", "emite_certificado", "palestrantes",
)

VERDADEIROS = {"sim", "s", "true", "1", "x"}


def _data(valor):
    """Aceita ISO ou `dd/mm/aaaa hh:mm` (com ou sem hora)."""
    texto = (valor or "").strip()
    if not texto:
        return None
    data = parse_datetime(texto)
    if data is None:
        for formato in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
            try:
                data = datetime.strptime(texto, formato)
                break
            except ValueError:
                continue
    if data is None:
        return None
    if timezone.is_naive(data):
        data = timezone.make_aware(data, timezone.get_current_timezone())
    return data


def _inteiro(valor, padrao=0):
    texto = (valor or "").strip()
    return int(texto) if texto.isdigit() else padrao


def _booleano(valor):
    return (valor or "").strip().lower() in VERDADEIROS


def importar_linhas(evento, linhas, publicada=True):
    """Núcleo: linhas já lidas (dict, chaves normalizadas) -> relatório.

    `publicada=False` cria as atividades como rascunho (usado pelo copiloto, que
    propõe um plano inicial para revisão). Na atualização de uma linha existente
    a visibilidade não é alterada.
    """
    relatorio = {"total": len(linhas or []), "criadas": 0, "atualizadas": 0,
                 "erros": 0, "linhas": []}

    for indice, linha in enumerate(linhas or [], start=1):
        linha = {k: (v or "").strip() for k, v in (linha or {}).items()}
        item = {"indice": indice, "titulo": linha.get("titulo", ""),
                "status": None, "motivo": "", "avisos": []}

        def terminar(status, motivo=""):
            item["status"] = status
            item["motivo"] = motivo
            relatorio[status] = relatorio.get(status, 0) + 1
            relatorio["linhas"].append(item)

        titulo = linha.get("titulo", "")
        if not titulo:
            terminar("erros", "linha sem título.")
            continue

        inicio = _data(linha.get("inicio"))
        fim = _data(linha.get("fim"))
        if inicio is None or fim is None:
            terminar("erros", "início/fim inválidos (use 'dd/mm/aaaa hh:mm' ou ISO).")
            continue
        if fim <= inicio:
            terminar("erros", "o fim precisa ser depois do início.")
            continue

        tipo = None
        nome_tipo = linha.get("tipo", "")
        if nome_tipo:
            tipo = TipoAtividade.objects.filter(nome__iexact=nome_tipo).first()
            if tipo is None:
                terminar("erros", f"tipo '{nome_tipo}' não existe (crie antes de importar).")
                continue

        palestrantes = []
        for email in (linha.get("palestrantes", "").replace(";", ",")).split(","):
            email = email.strip()
            if not email:
                continue
            pessoa = Participante.objects.filter(email__iexact=email).first()
            if pessoa is None:
                item["avisos"].append(f"palestrante '{email}' não tem conta — ignorado.")
                continue
            palestrantes.append(pessoa)

        dados = {
            "descricao": linha.get("descricao", ""),
            "tipo": tipo,
            "local": linha.get("local", ""),
            "n_vagas": _inteiro(linha.get("n_vagas")),
            "emite_certificado": _booleano(linha.get("emite_certificado")),
        }

        # Chave de idempotência: título + início.
        atividade = Atividade.objects.filter(
            evento=evento, titulo=titulo, data_hora_inicio=inicio
        ).first()
        if atividade is None:
            atividade = Atividade.objects.create(
                evento=evento, titulo=titulo,
                data_hora_inicio=inicio, data_hora_fim=fim,
                publicada=publicada, **dados,
            )
            terminar("criadas")
        else:
            for campo, valor in dados.items():
                setattr(atividade, campo, valor)
            atividade.data_hora_fim = fim
            atividade.save()
            terminar("atualizadas")

        if palestrantes:
            atividade.palestrantes.set(palestrantes)

    return relatorio


def importar_arquivo(evento, caminho):
    """Lê o arquivo (csv/xls/xlsx) e importa para o evento."""
    from .roster import ler_arquivo

    return importar_linhas(evento, ler_arquivo(caminho))
