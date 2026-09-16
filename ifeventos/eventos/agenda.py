"""Monta a grade (cronograma semanal) da programação de um evento.

A lista de atividades já existe em `programacao.html`; esta grade é uma
visualização alternativa: colunas = dias do evento, linhas = horas. Cada
atividade aparece na linha do seu horário de início, com o intervalo de tempo
no rótulo — atividades que começam no mesmo horário (sobreposição) são
empilhadas na mesma célula.

Quando o evento passa de 7 dias, devolve uma grade por SEMANA (seções), em vez
de uma faixa enorme de colunas.

Devolve só estruturas prontas para o template (nada de acesso a tuplas):

    {
      "vazio": bool,
      "total": int,
      "semanas": [
        {"rotulo": "05/10 – 09/10",
         "colunas": [{"data": date, "rotulo": "Seg", "curta": "05/10", "hoje": bool}],
         "linhas": [{"rotulo": "07:00", "celulas": [[atividade, ...], ...]}]},
      ],
    }

`celulas` é paralelo a `colunas` (mesma ordem).
"""

from datetime import date, timezone as dt_timezone
import unicodedata

from django.utils import timezone

# Índice de `date.weekday()` (0 = segunda) -> rótulo curto.
DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

# Eventos com mais dias que isto são quebrados em semanas.
DIAS_POR_GRADE = 7

# Sem local informado no evento/atividade.
SEM_LOCAL = "Sem local definido"

ORDENS = ("dia", "local", "titulo")
ORDEM_PADRAO = "dia"


def _sem_acento(texto):
    """Minúsculas e sem acento — para ordenar/comparar de forma previsível."""
    base = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in base if unicodedata.category(c) != "Mn")


def _aliases():
    """Apelidos de local configurados pela escola (settings)."""
    from django.conf import settings

    return getattr(settings, "AGENDA_ALIASES_LOCAL", None) or {}


def locais_de(atividade):
    """Lugares da atividade: `local` é texto livre, com vários separados por vírgula.

    Aplica os apelidos (`AGENDA_ALIASES_LOCAL`) e remove repetições, para o
    filtro e o agrupamento falarem de um lugar só.
    """
    aliases = _aliases()
    lugares = []
    for parte in (atividade.local or "").split(","):
        nome = parte.strip()
        if not nome:
            continue
        nome = aliases.get(nome, nome)
        if nome not in lugares:
            lugares.append(nome)
    return lugares


def locais_do_evento(atividades):
    """Lista de locais distintos (com contagem) para o filtro: [{nome, total}]."""
    total = {}
    for atividade in atividades or []:
        for nome in locais_de(atividade):
            total[nome] = total.get(nome, 0) + 1
    return [{"nome": nome, "total": total[nome]} for nome in sorted(total, key=_sem_acento)]


def _cores_por_tipo(atividades):
    """Classe de cor estável por tipo (mesmo tipo = mesma cor dentro do evento)."""
    tipos = sorted({a.tipo_id for a in atividades or [] if a.tipo_id})
    return {tipo_id: f"agenda-tipo-{i % 6}" for i, tipo_id in enumerate(tipos)}


def anotar(atividades):
    """Acrescenta às atividades dados derivados usados no template/filtro.

    - `agenda_cor`: classe de cor pelo tipo;
    - `agenda_locais`: lugares separados por `|` (o filtro compara assim).
    """
    itens = list(atividades or [])
    cores = _cores_por_tipo(itens)
    for atividade in itens:
        atividade.agenda_cor = cores.get(atividade.tipo_id, "agenda-sem-tipo")
        atividade.agenda_locais = "|".join(locais_de(atividade))
    return itens



def tipos_do_evento(atividades):
    """Tipos presentes (com contagem e cor) para o filtro e a legenda.

    [{id, nome, total, cor}]
    """
    itens = list(atividades or [])
    cores = _cores_por_tipo(itens)
    contagem = {}
    nomes = {}
    for atividade in itens:
        if not atividade.tipo_id:
            continue
        contagem[atividade.tipo_id] = contagem.get(atividade.tipo_id, 0) + 1
        nomes[atividade.tipo_id] = getattr(atividade.tipo, "nome", "") or ""
    return [
        {"id": tid, "nome": nomes[tid], "total": contagem[tid], "cor": cores.get(tid, "agenda-sem-tipo")}
        for tid in sorted(nomes, key=lambda t: _sem_acento(nomes[t]))
    ]


def _hora_local(atividade):
    return timezone.localtime(atividade.data_hora_inicio)


def agrupar(atividades, ordem=ORDEM_PADRAO):
    """Seções da LISTA: por dia (padrão), por local ou por título.

    Devolve [{rotulo, itens, total}] — `rotulo` é None quando não há cabeçalho
    (ordenação por título). Em “local”, a atividade aparece sob CADA lugar que
    ocupa (o `local` é uma lista separada por vírgula), então a mesma atividade
    pode aparecer em mais de uma seção.
    """
    if ordem not in ORDENS:
        ordem = ORDEM_PADRAO
    itens = list(atividades or [])
    if not itens:
        return []

    if ordem == "titulo":
        return [{
            "rotulo": None,
            "itens": sorted(itens, key=lambda a: _sem_acento(a.titulo)),
            "total": len(itens),
        }]

    if ordem == "local":
        # Cada atividade entra sob CADA lugar que ela ocupa (o `local` é uma
        # lista). Assim "Auditório" mostra tudo que passa por lá, inclusive as
        # atividades que também usam outros espaços.
        grupos = {}
        for atividade in itens:
            lugares = list(dict.fromkeys(locais_de(atividade))) or [SEM_LOCAL]
            for lugar in lugares:
                grupos.setdefault(lugar, []).append(atividade)
        return [
            {"rotulo": chave, "itens": sorted(grupos[chave], key=_hora_local),
             "total": len(grupos[chave])}
            for chave in sorted(grupos, key=_sem_acento)
        ]

    # dia (padrão)
    grupos = {}
    for atividade in itens:
        grupos.setdefault(_hora_local(atividade).date(), []).append(atividade)
    return [
        {
            "rotulo": f"{DIAS_SEMANA[dia.weekday()]} {dia.strftime('%d/%m')}",
            "itens": sorted(grupos[dia], key=_hora_local),
            "total": len(grupos[dia]),
            "hoje": dia == timezone.localdate(),
        }
        for dia in sorted(grupos)
    ]



def _intervalo(ini, fim):
    """Horas (linhas) que a atividade ocupa: início e fim, em hora cheia.

    Fim em ponto (12:00) não ocupa a hora 12; fim com minutos (12:05) ocupa.
    """
    inicio = ini.hour
    fim_hora = fim.hour if (fim.minute or fim.second or fim.microsecond) else fim.hour - 1
    if fim_hora < inicio:
        fim_hora = inicio
    return inicio, fim_hora


def _grupos_de_dias(dias):
    """Uma lista de dias, ou uma por semana quando passa de `DIAS_POR_GRADE`."""
    if len(dias) <= DIAS_POR_GRADE:
        return [dias]
    semanas = []
    atual = []
    chave = None
    for dia in dias:
        iso = dia.isocalendar()[:2]
        if chave is not None and iso != chave:
            semanas.append(atual)
            atual = []
        chave = iso
        atual.append(dia)
    if atual:
        semanas.append(atual)
    return semanas


def montar_grade(atividades):
    """De atividades (queryset/lista) para a estrutura da grade."""
    itens = []
    for atividade in atividades or []:
        ini = timezone.localtime(atividade.data_hora_inicio)
        fim = timezone.localtime(atividade.data_hora_fim)
        itens.append((ini, fim, atividade))

    if not itens:
        return {"vazio": True, "total": 0, "semanas": []}

    inicio_por_dia = {}
    for ini, _fim, atividade in itens:
        inicio_por_dia.setdefault(ini.date(), []).append((ini, atividade))

    dia_por_hora = {}
    h_min = min(ini.hour for ini, _f, _a in itens)
    h_max = 0
    for ini, fim, atividade in itens:
        _i, f = _intervalo(ini, fim)
        h_max = max(h_max, f)
        dia_por_hora.setdefault((ini.date(), ini.hour), []).append(atividade)

    horas = list(range(h_min, h_max + 1))
    hoje = timezone.localdate()

    # Cor do chip por tipo e lugares (para o filtro/legenda).
    anotar([a for _i, _f, a in itens])

    semanas = []
    for grupo in _grupos_de_dias(sorted(inicio_por_dia)):
        colunas = [
            {
                "data": dia,
                "iso": dia.strftime("%Y-%m-%d"),
                "rotulo": DIAS_SEMANA[dia.weekday()],
                "curta": dia.strftime("%d/%m"),
                "hoje": dia == hoje,
            }
            for dia in grupo
        ]
        linhas = [
            {
                "rotulo": f"{hora:02d}:00",
                "celulas": [
                    {"coluna": col, "atividades": dia_por_hora.get((col["data"], hora), [])}
                    for col in colunas
                ],
            }
            for hora in horas
        ]
        semanas.append({
            "rotulo": (
                f"{grupo[0].strftime('%d/%m')} – {grupo[-1].strftime('%d/%m')}"
                if len(grupo) > 1 else grupo[0].strftime("%d/%m")
            ),
            "colunas": colunas,
            "linhas": linhas,
        })

    return {"vazio": False, "total": len(itens), "semanas": semanas}


# ---------------------------------------------------------------------------
# Exportação .ics (adicionar ao calendário)
# ---------------------------------------------------------------------------

def _ics_escapar(texto):
    """Escapa o texto conforme a RFC 5545 (\\ ; , e quebras de linha)."""
    return (
        str(texto or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
    )


def _ics_dobrar(linha):
    """RFC 5545: linhas de até 75 octetos; a continuação começa com espaço."""
    pedacos = []
    atual = ""
    for caracter in linha:
        if len((atual + caracter).encode("utf-8")) > 75:
            pedacos.append(atual)
            atual = " " + caracter
        else:
            atual += caracter
    pedacos.append(atual)
    return "\r\n".join(pedacos)


def _ics_data(valor):
    """Data/hora em UTC no formato do iCalendar (…Z)."""
    return valor.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def montar_ics(evento, atividades):
    """Conteúdo `.ics` com um VEVENT por atividade (para o calendário)."""
    carimbo = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    linhas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//IF Eventos//Programacao//PT-BR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_ics_escapar(evento.title)}",
    ]
    for atividade in atividades or []:
        local = (atividade.local or "").strip() or (evento.local or "")
        descricao = atividade.descricao or ""
        tipo = getattr(atividade.tipo, "nome", "") or ""
        if tipo:
            descricao = f"[{tipo}] {descricao}"
        linhas += [
            "BEGIN:VEVENT",
            f"UID:{atividade.codigo_confirmacao}@ifeventos",
            f"DTSTAMP:{carimbo}",
            f"DTSTART:{_ics_data(atividade.data_hora_inicio)}",
            f"DTEND:{_ics_data(atividade.data_hora_fim)}",
            f"SUMMARY:{_ics_escapar(atividade.titulo)}",
            f"LOCATION:{_ics_escapar(local)}",
            f"DESCRIPTION:{_ics_escapar(descricao)}",
            "END:VEVENT",
        ]
    linhas.append("END:VCALENDAR")
    return "\r\n".join(_ics_dobrar(linha) for linha in linhas) + "\r\n"
