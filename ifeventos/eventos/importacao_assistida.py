"""Importação assistida da programação (copiloto do organizador).

Diferente de `importacao_programacao` (que exige o cabeçalho canônico), aqui o
organizador sobe a planilha que ele já tem — muitas vezes de um Google Forms,
com títulos de coluna livres — e o sistema **propõe o mapeamento** das colunas
para os campos de `Atividade`. O organizador revisa, ajusta e confirma; só
então a programação é gravada (reusando `importacao_programacao.importar_linhas`,
mantendo idempotência por título + início).

Sem IA, o mapeamento cai num dicionário de sinônimos (determinístico). Nada é
gravado sem a confirmação do organizador.
"""

import os
import re
import tempfile
import uuid
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from . import importacao_programacao
from . import services
from .models import sem_acento

# Prefixo da chave de cache onde o arquivo lido fica entre as etapas.
CACHE_PREFIXO = "importacao_prog_"
CACHE_SEGUNDOS = 1800
MAX_LINHAS = 1000

# Campos de `Atividade` que a importação reconhece.
# (chave, rótulo, obrigatório, ajuda)
CAMPOS = [
    ("titulo", "Título", True, "Nome da atividade."),
    ("descricao", "Descrição", False, "Texto apresentado ao público."),
    ("tipo", "Tipo", False, "Precisa existir no catálogo de tipos."),
    ("local", "Local", False, "Sala/auditório (texto)."),
    ("inicio", "Início", False, "Data e hora de início (ex.: 26/10/2026 08:00)."),
    ("fim", "Fim", False, "Data e hora de término."),
    ("data", "Dia/Data", False, "Usado com Hora de início/fim ou Turno."),
    ("hora_inicio", "Hora de início", False, "Ex.: 08:00."),
    ("hora_fim", "Hora de término", False, "Ex.: 12:00."),
    ("turno", "Turno", False, "Manhã, tarde ou noite (quando não há hora)."),
    ("n_vagas", "Nº de vagas", False, "Número inteiro."),
    ("emite_certificado", "Emite certificado", False, "Sim/Não."),
    ("palestrantes", "Palestrantes (e-mail)", False, "E-mails separados por ; ou ,."),
]

CAMPOS_CANONICOS = {chave for chave, _, _, _ in CAMPOS}
OBRIGATORIO = {chave for chave, _, obrig, _ in CAMPOS if obrig}

# Sinônimos normalizados (sem acento, minúsculos) por campo canônico.
SINONIMOS = {
    "titulo": ["titulo", "titulo da atividade", "atividade", "nome", "nome da atividade",
               "tema", "titulo da proposta"],
    "descricao": ["descricao", "descricao da atividade", "resumo", "detalhes", "sobre",
                  "ementa"],
    "tipo": ["tipo", "tipo de atividade", "categoria", "modalidade", "natureza"],
    "local": ["local", "local adequado", "sala", "espaco", "auditorio", "laboratorio"],
    "inicio": ["inicio", "data inicio", "data de inicio", "comeca", "data e hora de inicio",
               "inicio da atividade"],
    "fim": ["fim", "data fim", "data de termino", "termina", "data e hora de termino",
            "fim da atividade", "termino"],
    "data": ["dia", "data", "data da atividade", "dia da atividade"],
    "hora_inicio": ["hora inicio", "hora de inicio", "horario de inicio", "hora"],
    "hora_fim": ["hora fim", "hora de termino", "horario de termino", "horario final"],
    "turno": ["turno", "periodo", "horario"],
    "n_vagas": ["n vagas", "n de vagas", "numero de vagas", "vagas", "lotacao",
                "capacidade"],
    "emite_certificado": ["emite certificado", "certificado", "certificacao",
                          "emite certificacao"],
    "palestrantes": ["palestrantes", "palestrante", "responsavel", "responsaveis",
                     "proponente", "autores", "email do palestrante", "contato"],
}

# Turnos padrão do campus (usados quando a planilha só traz o turno).
TURNOS = {
    "manha": ("08:00", "12:00"),
    "tarde": ("13:30", "17:30"),
    "noite": ("18:30", "22:30"),
    "integral": ("08:00", "18:00"),
}

FORMATOS_DATA = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y")


def _norm(texto):
    return " ".join(sem_acento(texto).split())


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------

def ler_upload(arquivo):
    """Lê o arquivo enviado (.csv/.xls/.xlsx) e devolve (cabeçalhos, linhas).

    Os cabeçalhos já vêm normalizados pelo leitor do roster (minúsculos, sem
    acento). Salva em arquivo temporário porque xlrd/openpyxl leem por caminho.
    """
    from .roster import ler_arquivo

    sufixo = os.path.splitext(getattr(arquivo, "name", "") or "")[1].lower() or ".csv"
    descritor, caminho = tempfile.mkstemp(suffix=sufixo)
    try:
        with os.fdopen(descritor, "wb") as destino:
            for bloco in arquivo.chunks():
                destino.write(bloco)
        linhas = ler_arquivo(caminho)
    finally:
        try:
            os.unlink(caminho)
        except OSError:
            pass

    cabecalhos = []
    for linha in linhas:
        for chave in linha:
            if chave and chave not in cabecalhos:
                cabecalhos.append(chave)
    return cabecalhos[:80], linhas[:MAX_LINHAS]


# ---------------------------------------------------------------------------
# Mapeamento de colunas
# ---------------------------------------------------------------------------

def mapear_por_sinonimos(cabecalhos):
    """Mapeamento determinístico cabeçalho → campo canônico.

    Primeiro casa o nome exato; depois tenta conter/estar contido num sinônimo.
    Devolve `{campo_canonico: cabecalho}`.
    """
    normalizados = {h: _norm(h) for h in cabecalhos}
    usados = set()
    mapa = {}

    for canonico in CAMPOS_CANONICOS:
        for sinonimo in SINONIMOS.get(canonico, []) + [canonico]:
            for cabecalho, chave in normalizados.items():
                if cabecalho in usados:
                    continue
                if chave == sinonimo:
                    mapa[canonico] = cabecalho
                    usados.add(cabecalho)
                    break
            if canonico in mapa:
                break

    for cabecalho, chave in normalizados.items():
        if cabecalho in usados:
            continue
        for canonico in CAMPOS_CANONICOS:
            if canonico in mapa:
                continue
            sinonimos = SINONIMOS.get(canonico, []) + [canonico]
            if any(len(s) > 3 and (s in chave or chave in s) for s in sinonimos):
                mapa[canonico] = cabecalho
                usados.add(cabecalho)
                break
    return mapa


def validar_mapeamento(mapeamento, cabecalhos):
    """Erros/avisos do mapeamento escolhido pelo organizador."""
    erros, avisos = [], []
    origens = [valor for valor in mapeamento.values() if valor]
    repetidas = {o for o in origens if origens.count(o) > 1}
    if repetidas:
        erros.append("A(s) coluna(s) %s foram usadas em mais de um campo." % ", ".join(sorted(repetidas)))
    for canonico, origem in mapeamento.items():
        if canonico not in CAMPOS_CANONICOS:
            erros.append("Campo desconhecido: %s." % canonico)
        if origem and origem not in cabecalhos:
            erros.append("Coluna '%s' não existe no arquivo." % origem)
    if not mapeamento.get("titulo"):
        erros.append("Mapeie a coluna do título — ela é obrigatória.")
    if not (mapeamento.get("inicio") or mapeamento.get("data")):
        avisos.append("Sem 'Início' nem 'Dia/Data': as linhas vão falhar por falta de horário.")
    return erros, avisos


# ---------------------------------------------------------------------------
# Mapeamento por IA (opcional; a rede de segurança é o dicionário acima)
# ---------------------------------------------------------------------------

def _prompt_mapeamento(cabecalhos, amostras, tipos, evento):
    campos = "\n".join("- %s: %s %s" % (chave, ajuda, "(obrigatório)" if obrig else "")
                       for chave, _rot, obrig, ajuda in CAMPOS)
    return """Você ajuda a importar a programação de um evento de um campus do IFMG.

Evento: {titulo} (tema: {categoria})
Tipos de atividade já cadastrados: {tipos}

Colunas do arquivo enviado: {cabecalhos}

Amostra das primeiras linhas (JSON):
{amostras}

Campos de destino possíveis:
{campos}

Mapeie cada coluna do arquivo para UM campo de destino, quando houver
correspondência clara. NÃO invente colunas que não existem. Ignore colunas que
não correspondem a nenhum campo.

Responda SOMENTE com JSON neste formato:
{{"mapeamento": {{"<campo_destino>": "<coluna_do_arquivo>"}}}}""".format(
        titulo=evento.title,
        categoria=evento.get_categoria_display(),
        tipos=", ".join(t.nome for t in tipos) or "(nenhum)",
        cabecalhos=", ".join(cabecalhos),
        amostras=amostras,
        campos=campos,
    )


def sanitizar_mapeamento_ia(dados, cabecalhos):
    """Valida o mapeamento vindo da IA contra os campos e colunas reais."""
    limpo = {}
    if not isinstance(dados, dict):
        return limpo
    valores = dados.get("mapeamento") if isinstance(dados.get("mapeamento"), dict) else dados
    usados = set()
    for canonico, origem in (valores or {}).items():
        canonico = str(canonico or "").strip()
        origem = str(origem or "").strip()
        if canonico not in CAMPOS_CANONICOS or canonico in limpo:
            continue
        if origem not in cabecalhos or origem in usados:
            continue
        limpo[canonico] = origem
        usados.add(origem)
    return limpo


async def sugerir_mapeamento(cabecalhos, amostras, tipos, evento):
    """Mapeamento sugerido: sinônimos primeiro; IA completa o que faltar.

    Devolve `{"mapeamento": {...}, "origem": "ia"|"sinonimos"|None, "aviso": str}`.
    """
    mapa = mapear_por_sinonimos(cabecalhos)
    faltam_colunas = [c for c in cabecalhos if c not in mapa.values()]
    faltam_campos = [c for c in CAMPOS_CANONICOS if c not in mapa]
    origem, aviso = "sinonimos", ""

    if faltam_colunas and faltam_campos:
        try:
            client = services.get_openai_client()
            resposta = await client.chat.completions.create(
                model=settings.IA_MODELO_CLASSIFICACAO,
                messages=[{"role": "system", "content": _prompt_mapeamento(
                    cabecalhos, amostras, tipos, evento
                )}],
                max_tokens=800,
                temperature=0,
                response_format={"type": "json_object"},
            )
            services.registrar_uso_ia(
                "importacao_mapeamento", settings.IA_MODELO_CLASSIFICACAO, resposta
            )
            dados = __import__("json").loads(resposta.choices[0].message.content or "{}")
            for canonico, coluna in sanitizar_mapeamento_ia(dados, cabecalhos).items():
                if canonico not in mapa:
                    mapa[canonico] = coluna
            origem = "ia"
        except Exception as erro:  # noqa: BLE001 - IA é acessória
            aviso = "A IA não está disponível agora; usei o mapeamento por sinônimos (%s)." % erro

    return {"mapeamento": mapa, "origem": origem, "aviso": aviso}


# ---------------------------------------------------------------------------
# Montagem das linhas canônicas
# ---------------------------------------------------------------------------

def _parse_data(valor, ano_padrao=None):
    texto = (valor or "").strip()
    if not texto:
        return None
    for formato in FORMATOS_DATA:
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    # "26/10" sem ano: usa o ano do evento.
    achado = re.match(r"^(\d{1,2})[/-](\d{1,2})$", texto)
    if achado and ano_padrao:
        return datetime(ano_padrao, int(achado.group(2)), int(achado.group(1))).date()
    return None


def _parse_hora(valor):
    texto = (valor or "").strip().lower().replace("h", ":")
    achado = re.match(r"^(\d{1,2})(?::(\d{2}))?$", texto)
    if not achado:
        return None
    hora, minuto = int(achado.group(1)), int(achado.group(2) or 0)
    if 0 <= hora <= 23 and 0 <= minuto <= 59:
        return "%02d:%02d" % (hora, minuto)
    return None


def _combinar(data, hora, ano_padrao):
    dia = _parse_data(data, ano_padrao)
    if dia is None or not hora:
        return ""
    return "%s %s" % (dia.strftime("%d/%m/%Y"), hora)


def montar_linha(canonica, evento):
    """Converte uma linha já mapeada na linha canônica da importação."""
    ano = evento.data_inicio.year if getattr(evento, "data_inicio", None) else None
    data = canonica.get("data", "")
    turno = _norm(canonica.get("turno", ""))
    limites = TURNOS.get(turno, ("", ""))

    inicio = (canonica.get("inicio") or "").strip()
    if not inicio:
        hora_inicio = _parse_hora(canonica.get("hora_inicio", "")) or limites[0]
        inicio = _combinar(data, hora_inicio, ano)

    fim = (canonica.get("fim") or "").strip()
    if not fim:
        hora_fim = _parse_hora(canonica.get("hora_fim", "")) or limites[1]
        fim = _combinar(data, hora_fim, ano) or inicio
    if not inicio:
        inicio = fim

    return {
        "titulo": (canonica.get("titulo") or "").strip(),
        "descricao": (canonica.get("descricao") or "").strip(),
        "tipo": (canonica.get("tipo") or "").strip(),
        "local": (canonica.get("local") or "").strip(),
        "inicio": inicio,
        "fim": fim,
        "n_vagas": (canonica.get("n_vagas") or "").strip(),
        "emite_certificado": (canonica.get("emite_certificado") or "").strip(),
        "palestrantes": (canonica.get("palestrantes") or "").strip(),
    }


def aplicar_mapeamento(linhas, mapeamento, evento):
    """Aplica o mapeamento {campo: coluna} e devolve as linhas canônicas."""
    canonicas = []
    for linha in linhas or []:
        base = {
            canonico: linha.get(origem, "")
            for canonico, origem in (mapeamento or {}).items()
            if origem
        }
        canonicas.append(montar_linha(base, evento))
    return canonicas


def previsualizar(evento, linhas_canonicas):
    """Relatório da importação SEM gravar (roda dentro de uma transação revertida)."""
    with transaction.atomic():
        relatorio = importacao_programacao.importar_linhas(evento, linhas_canonicas)
        transaction.set_rollback(True)
    return relatorio


def guardar(token, dados):
    cache.set(CACHE_PREFIXO + token, dados, CACHE_SEGUNDOS)


def recuperar(token):
    return cache.get(CACHE_PREFIXO + token)


def novo_token():
    return uuid.uuid4().hex


def campos_com_selecao(mapeamento):
    """Campos canônicos com o cabeçalho atualmente selecionado (para a tela)."""
    mapeamento = mapeamento or {}
    return [
        {"chave": chave, "rotulo": rotulo, "obrigatorio": obrig, "ajuda": ajuda,
         "origem": mapeamento.get(chave, "")}
        for chave, rotulo, obrig, ajuda in CAMPOS
    ]
