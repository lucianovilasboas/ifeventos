"""Certificados: elegibilidade, contexto e renderização (modo fundo).

Este módulo concentra as regras que antes estavam soltas nas views e no
`utils.gerar_certificado`:

- **Elegibilidade**: quem tem direito ao certificado de uma atividade (a
  atividade emite certificado + a pessoa participou) e ao certificado do evento
  (percentual mínimo de presença nas atividades que emitem certificado).
- **Contexto**: as variáveis que o texto do certificado pode usar.
- **Renderização**: gera o PDF no modo "fundo" (imagem de pano de fundo +
  texto/assinaturas/QR desenhados com reportlab). O modo ".docx" entra na fase
  seguinte.

O QR aponta para a verificação pública já existente (`/c/<token>/`).
"""

from __future__ import annotations

import io
import logging
import subprocess
from datetime import datetime

from django.db.models import Count
from django.utils import timezone
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from . import metadados
from .models import Atividade, Certificado, Inscricao, Participante, Presenca, FUNCAO_CHOICES
from .tempo import local_legivel
from .validators import formatar_cpf

logger = logging.getLogger(__name__)


class LibreOfficeIndisponivel(RuntimeError):
    """O binário do LibreOffice não está instalado neste servidor."""


class CertificadoLayoutError(RuntimeError):
    """O layout escolhido (ex.: .docx) não pôde ser gerado."""

# ---------------------------------------------------------------------------
# Elegibilidade
# ---------------------------------------------------------------------------


def _participou(participante_id, atividade_id) -> bool:
    """Participou = tem presença; fallback = inscrição confirmada."""
    return (
        Presenca.objects.filter(
            participante_id=participante_id, atividade_id=atividade_id
        ).exists()
        or Inscricao.objects.filter(
            participante_id=participante_id,
            atividade_id=atividade_id,
            confirmada=True,
        ).exists()
    )


def participantes_da_atividade(atividade):
    """Quem tem direito ao certificado DESTA atividade.

    A atividade precisa emitir certificado; a pessoa precisa ter presença (ou
    inscrição confirmada). Devolve um queryset de Participante.
    """
    if not getattr(atividade, "emite_certificado", False):
        return Participante.objects.none()

    ids = set(
        Presenca.objects.filter(atividade=atividade).values_list(
            "participante_id", flat=True
        )
    ) | set(
        Inscricao.objects.filter(
            atividade=atividade, confirmada=True
        ).values_list("participante_id", flat=True)
    )
    return Participante.objects.filter(id__in=ids)


def participantes_da_funcao(evento, funcao):
    """Quem tem direito ao certificado DE UMA FUNÇÃO.

    Funções: organizador (dono + co-organizadores), palestrante (palestrantes
    das atividades), equipe (equipe de apoio) e comissao. Não exige presença —
    basta o vínculo com o evento. Devolve um queryset de Participante.
    """
    ids = set()
    if funcao == "organizador":
        if evento.organizador_id:
            ids.add(evento.organizador_id)
        ids |= set(evento.organizadores.values_list("id", flat=True))
    elif funcao == "palestrante":
        ids = set(evento.atividades.values_list("palestrantes__id", flat=True))
    elif funcao == "equipe":
        ids = set(evento.equipe.values_list("id", flat=True))
    elif funcao == "comissao":
        ids = set(evento.comissao.values_list("id", flat=True))
    ids.discard(None)
    return Participante.objects.filter(id__in=ids)


def atividades_do_palestrante(evento, participante):
    """Atividades do evento em que a pessoa é palestrante (ordem cronológica)."""
    if evento is None or participante is None:
        return Atividade.objects.none()
    return (
        evento.atividades.filter(palestrantes=participante)
        .select_related("tipo")
        .order_by("data_hora_inicio", "id")
    )


def _rotulo_tipo(atividade):
    """Rótulo do tipo da atividade (catálogo → sugerido → genérico)."""
    if atividade.tipo_id:
        return atividade.tipo.nome
    return atividade.tipo_sugerido or "Atividade"


def _pluralizar(rotulo, n):
    """Plural simples do rótulo do tipo quando há mais de uma atividade.

    Adiciona "s" às palavras que não terminam em "s", preservando conectores
    (`de`, `da`, `do`, `das`, `dos`, `e`). Ex.: `Mesa Redonda` → `Mesas Redondas`.
    """
    if n <= 1:
        return rotulo
    conectores = {"de", "da", "do", "das", "dos", "e"}
    palavras = []
    for palavra in rotulo.split():
        if palavra.lower() in conectores or palavra.endswith("s"):
            palavras.append(palavra)
        else:
            palavras.append(palavra + "s")
    return " ".join(palavras)


def _agrupar_texto(grupos):
    """Texto corrido agrupado por tipo: `2 Palestras (A; B) e 1 Minicurso (C)`."""
    partes = [
        f"{len(g['titulos'])} {_pluralizar(g['rotulo'], len(g['titulos']))} "
        f"({'; '.join(g['titulos'])})"
        for g in grupos
    ]
    if not partes:
        return ""
    if len(partes) == 1:
        return partes[0]
    return ", ".join(partes[:-1]) + " e " + partes[-1]


def participantes_do_evento(evento, config=None):
    """Quem tem direito ao certificado DO EVENTO (percentual de presença).

    O denominador são as atividades que emitem certificado. A pessoa precisa
    comparecer a, no mínimo, `percentual`% delas. Devolve um queryset.
    """
    percentual = (
        config.percentual_efetivo
        if config is not None
        else evento.percentual_certificado
    )
    atividades_ids = list(
        evento.atividades.filter(emite_certificado=True).values_list("id", flat=True)
    )
    total = len(atividades_ids)
    if total == 0:
        return Participante.objects.none()

    pres = Presenca.objects.filter(atividade_id__in=atividades_ids).values_list(
        "participante_id", "atividade_id"
    )
    insc = Inscricao.objects.filter(
        atividade_id__in=atividades_ids, confirmada=True
    ).values_list("participante_id", "atividade_id")

    por_pessoa: dict[int, set[int]] = {}
    for participante_id, atividade_id in list(pres) + list(insc):
        por_pessoa.setdefault(participante_id, set()).add(atividade_id)

    minimo = total * (percentual or 0) / 100.0
    ids = [pid for pid, feitas in por_pessoa.items() if len(feitas) >= minimo]
    return Participante.objects.filter(id__in=ids)


def percentual_participacao(participante, evento):
    """Percentual do participante nas atividades do evento que emitem certificado.

    Devolve um inteiro 0–100, ou None quando o evento não tem atividades que
    emitem certificado.
    """
    atividades_ids = list(
        evento.atividades.filter(emite_certificado=True).values_list("id", flat=True)
    )
    total = len(atividades_ids)
    if total == 0:
        return None

    pres = set(
        Presenca.objects.filter(
            participante=participante, atividade_id__in=atividades_ids
        ).values_list("atividade_id", flat=True)
    )
    insc = set(
        Inscricao.objects.filter(
            participante=participante,
            atividade_id__in=atividades_ids,
            confirmada=True,
        ).values_list("atividade_id", flat=True)
    )
    feitas = len(pres | insc)
    return round(feitas * 100 / total)


def _minutos_efetivos(atividade, config=None):
    """Minutos de carga horária: campo da atividade → fim−início → config.

    O evento NÃO entra aqui de propósito: o certificado do evento não tem carga
    horária (usa o percentual de participação).
    """
    if atividade is not None:
        if atividade.carga_horaria:
            return atividade.carga_horaria * 60
        if atividade.data_hora_inicio and atividade.data_hora_fim:
            delta = atividade.data_hora_fim - atividade.data_hora_inicio
            minutos = int(delta.total_seconds() // 60)
            if minutos > 0:
                return minutos
    if config is not None and config.carga_horaria_padrao:
        return config.carga_horaria_padrao * 60
    return None


def _formatar_carga(minutos):
    """Formata minutos como '2h', '2h30' ou '45min'."""
    if not minutos or minutos <= 0:
        return ""
    horas, resto = divmod(minutos, 60)
    if horas and resto:
        return f"{horas}h{resto:02d}"
    if horas:
        return f"{horas}h"
    return f"{resto}min"


def carga_horaria_efetiva(atividade, evento=None, config=None):
    """Carga horária em horas inteiras (para o registro do Certificado)."""
    minutos = _minutos_efetivos(atividade, config)
    if minutos is None:
        return None
    return max(1, round(minutos / 60))


# ---------------------------------------------------------------------------
# Configuração efetiva (evento, padrão de atividades e override por atividade)
# ---------------------------------------------------------------------------


def config_do_evento(evento):
    """Config usada no certificado DO EVENTO."""
    from .models import ConfiguracaoCertificado

    if evento is None:
        return None
    return ConfiguracaoCertificado.objects.filter(
        evento=evento,
        atividade__isnull=True,
        escopo=ConfiguracaoCertificado.ESCOPO_EVENTO,
    ).first()


def config_padrao_atividades(evento):
    """Config padrão dos certificados de atividade."""
    from .models import ConfiguracaoCertificado

    if evento is None:
        return None
    return ConfiguracaoCertificado.objects.filter(
        evento=evento,
        atividade__isnull=True,
        escopo=ConfiguracaoCertificado.ESCOPO_ATIVIDADE,
    ).first()


def config_da_funcao(evento, funcao):
    """Config usada no certificado DE UMA FUNÇÃO."""
    from .models import ConfiguracaoCertificado

    if evento is None or not funcao:
        return None
    return ConfiguracaoCertificado.objects.filter(
        evento=evento,
        atividade__isnull=True,
        escopo=ConfiguracaoCertificado.ESCOPO_FUNCAO,
        funcao=funcao,
    ).first()


def config_efetiva(atividade=None, evento=None, funcao=None):
    """Config a usar: override da atividade → padrão de atividades → do evento.

    Quando `funcao` é informada, devolve a config daquela função no evento.
    """
    from .models import ConfiguracaoCertificado

    if funcao:
        if evento is None and atividade is not None:
            evento = atividade.evento
        return config_da_funcao(evento, funcao)
    if atividade is not None:
        config = ConfiguracaoCertificado.objects.filter(atividade=atividade).first()
        if config is not None:
            return config
        evento = evento or atividade.evento
        return config_padrao_atividades(evento)
    return config_do_evento(evento)


# ---------------------------------------------------------------------------
# Contexto (variáveis do texto)
# ---------------------------------------------------------------------------

# Catálogo das variáveis — FONTE ÚNICA para o contexto e para a UI (seletor).
# Cada item: (chave, rótulo, escopo, docx_only).
#   escopo: None (todos) | "evento" | "atividade" | "funcao"
#   docx_only: só existe no modo .docx (imagens/assinaturas)
_VARIAVEIS = [
    ("Pessoa", [
        ("nome", "Nome completo", None, False),
        ("primeiro_nome", "Primeiro nome", None, False),
        ("sobrenome", "Sobrenome", None, False),
        ("cpf", "CPF (só dígitos)", None, False),
        ("cpf_mascara", "CPF com máscara (000.000.000-00)", None, False),
        ("email", "E-mail", None, False),
        ("telefone", "Telefone", None, False),
        ("funcao", "Função (organizador/palestrante/equipe/comissão)", "funcao", False),
    ]),
    ("Evento", [
        ("evento", "Título do evento", None, False),
        ("evento_local", "Local do evento", None, False),
        ("evento_data_inicio", "Data de início do evento", None, False),
        ("evento_data_fim", "Data de término do evento", None, False),
        ("evento_periodo", "Período do evento", None, False),
        ("evento_categoria", "Categoria do evento", None, False),
        ("evento_descricao", "Descrição do evento", None, False),
        ("evento_carga_horaria", "Carga horária do evento", None, False),
        ("organizador", "Nome do organizador", None, False),
    ]),
    ("Atividade", [
        ("atividade", "Título da atividade", "atividade", False),
        ("tipo_atividade", "Tipo da atividade", "atividade", False),
        ("atividade_local", "Local da atividade", "atividade", False),
        ("local", "Local (atividade ou evento)", None, False),
        ("atividade_data", "Data da atividade", "atividade", False),
        ("atividade_hora_inicio", "Hora de início", "atividade", False),
        ("atividade_hora_fim", "Hora de término", "atividade", False),
        ("atividade_inicio", "Início (data e hora)", "atividade", False),
        ("atividade_fim", "Término (data e hora)", "atividade", False),
        ("atividade_periodo", "Período da atividade", "atividade", False),
        ("atividade_descricao", "Descrição da atividade", "atividade", False),
        ("atividade_palestrantes", "Palestrantes", "atividade", False),
        ("carga_horaria", "Carga horária da atividade", "atividade", False),
    ]),
    ("Certificado", [
        ("data", "Data de emissão", None, False),
        ("hora_emissao", "Hora de emissão", None, False),
        ("qr_url", "URL de verificação", None, False),
        ("percentual_participacao", "Percentual de participação", "evento", False),
        ("percentual_minimo", "Percentual mínimo exigido", "evento", False),
    ]),
    ("Atividades do palestrante", [
        ("carga_horaria", "Carga horária total", "funcao:palestrante", False),
        ("carga_horaria_total", "Carga horária total (alias)", "funcao:palestrante", False),
        ("n_atividades", "Quantidade de atividades", "funcao:palestrante", False),
        ("atividades_lista", "Lista das atividades (tipo, título, carga, data)", "funcao:palestrante", False),
        ("atividades_texto", "Atividades em texto corrido", "funcao:palestrante", False),
        ("atividades_resumo", "Resumo por tipo", "funcao:palestrante", False),
    ]),
    ("Documento .docx (imagens e assinaturas)", [
        ("qr", "QR de verificação (imagem)", None, True),
        ("assinatura1", "Imagem da assinatura 1", None, True),
        ("assinatura2", "Imagem da assinatura 2", None, True),
        ("assinante1", "Nome do assinante 1", None, True),
        ("cargo_assinante1", "Cargo do assinante 1", None, True),
        ("assinante2", "Nome do assinante 2", None, True),
        ("cargo_assinante2", "Cargo do assinante 2", None, True),
    ]),
]


def variaveis_certificado(tipo, funcao=None):
    """Catálogo agrupado das variáveis disponíveis para um escopo.

    `tipo` ∈ {"evento", "atividade", "funcao"}. Quando `tipo == "funcao"`,
    `funcao` (código) habilita as variáveis específicas — hoje as do palestrante
    (`funcao:palestrante`). Inclui a lista dinâmica de metadados
    (`{{meta_<chave>}}`) configurados pela escola.
    """
    escopo_funcao = f"funcao:{funcao}" if funcao else None
    grupos = []
    for nome, itens in _VARIAVEIS:
        filtrados = [
            {"chave": chave, "rotulo": rotulo, "docx_only": docx_only}
            for chave, rotulo, escopo, docx_only in itens
            if escopo is None or escopo == tipo or (escopo_funcao and escopo == escopo_funcao)
        ]
        if filtrados:
            grupos.append({"grupo": nome, "itens": filtrados})

    meta = [
        {"chave": f"meta_{campo['chave']}", "rotulo": campo["rotulo"], "docx_only": False}
        for campo in metadados.campos()
    ]
    if meta:
        grupos.append({"grupo": "Metadados do participante", "itens": meta})
    return grupos


def _formata_data(valor):
    """Data (`dd/mm/aaaa`) aceitando date, datetime ou texto ISO."""
    if not valor:
        return ""
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return ""
    return valor.strftime("%d/%m/%Y")


def _metadados_contexto(participante):
    """Variáveis `meta_<chave>` a partir dos metadados configurados."""
    dados_obj = getattr(participante, "metadados", None)
    dados = dict(dados_obj.dados) if dados_obj else {}
    return {
        f"meta_{campo['chave']}": str(dados.get(campo["chave"], "") or "")
        for campo in metadados.campos()
    }


def contexto_certificado(
    participante, *, atividade=None, evento=None, config=None, funcao=None
):
    """Variáveis disponíveis no corpo/template do certificado."""
    if evento is None and atividade is not None:
        evento = atividade.evento
    if config is None:
        config = config_efetiva(atividade, evento, funcao)

    from .crachas import gerar_token, url_verificacao

    qr_url = url_verificacao(
        gerar_token(
            participante.id,
            evento_id=getattr(evento, "id", None),
            tipo="certificado",
            atividade_id=getattr(atividade, "id", None),
            funcao=funcao,
        )
    )
    tipo_atividade = ""
    if atividade is not None:
        if atividade.tipo_id:
            tipo_atividade = atividade.tipo.nome
        elif atividade.tipo_sugerido:
            tipo_atividade = atividade.tipo_sugerido

    # Rótulo da função (certificado por função).
    funcao_txt = ""
    if funcao:
        funcao_txt = dict(FUNCAO_CHOICES).get(funcao, funcao)

    # Carga horária existe só no certificado de ATIVIDADE.
    carga_horaria = ""
    if atividade is not None:
        carga_horaria = _formatar_carga(_minutos_efetivos(atividade, config))

    # Percentual de participação existe só no certificado do EVENTO.
    percentual_participacao_txt = ""
    percentual_minimo_txt = ""
    if atividade is None and evento is not None and not funcao:
        valor = percentual_participacao(participante, evento)
        if valor is not None:
            percentual_participacao_txt = f"{valor}%"
        minimo = (
            config.percentual_efetivo
            if config is not None
            else evento.percentual_certificado
        )
        percentual_minimo_txt = f"{minimo}%"

    # -- Datas e horários -----------------------------------------------------
    evento_data_inicio = _formata_data(getattr(evento, "data_inicio", None))
    evento_data_fim = _formata_data(getattr(evento, "data_fim", None))
    evento_periodo = ""
    if evento is not None:
        from .crachas import periodo_legivel

        evento_periodo = periodo_legivel(evento)

    atividade_data = atividade_hora_inicio = atividade_hora_fim = ""
    atividade_inicio = atividade_fim = atividade_periodo = ""
    if atividade is not None:
        atividade_data = local_legivel(atividade.data_hora_inicio, "%d/%m/%Y")
        atividade_hora_inicio = local_legivel(atividade.data_hora_inicio, "%H:%M")
        atividade_hora_fim = local_legivel(atividade.data_hora_fim, "%H:%M")
        atividade_inicio = local_legivel(atividade.data_hora_inicio)
        atividade_fim = local_legivel(atividade.data_hora_fim)
        if atividade_inicio and atividade_hora_fim:
            atividade_periodo = f"{atividade_inicio} às {atividade_hora_fim}"

    # -- Textos e campos derivados -------------------------------------------
    evento_local = evento.local if evento is not None else ""
    evento_categoria = evento.get_categoria_display() if evento is not None else ""
    evento_descricao = evento.description if evento is not None else ""
    evento_carga_horaria = ""
    if evento is not None and evento.carga_horaria:
        evento_carga_horaria = _formatar_carga(evento.carga_horaria * 60)
    organizador = ""
    if evento is not None and evento.organizador_id:
        organizador = evento.organizador.get_full_name() or evento.organizador.email

    atividade_local = atividade.local if atividade is not None else ""
    atividade_descricao = atividade.descricao if atividade is not None else ""
    atividade_palestrantes = ""
    if atividade is not None:
        atividade_palestrantes = ", ".join(
            (p.get_full_name() or p.email) for p in atividade.palestrantes.all()
        )

    nome = participante.get_full_name()
    evento_titulo = evento.title if evento is not None else ""
    atividade_titulo = atividade.titulo if atividade is not None else ""
    local = (
        atividade.local
        if (atividade is not None and atividade.local)
        else evento_local
    )
    emitido_em = timezone.localtime()
    data_emissao = emitido_em.strftime("%d/%m/%Y")
    hora_emissao = emitido_em.strftime("%H:%M")

    # -- Certificado do PALESTRANTE: agrega as atividades dele ----------------
    # Um único certificado para todas as atividades: lista (tipo, título, carga)
    # e soma da carga horária. Só se aplica à função "palestrante".
    carga_horaria_total_txt = ""
    n_atividades_txt = ""
    atividades_lista = ""
    atividades_resumo = ""
    atividades_texto = ""
    atividades = []
    if funcao == "palestrante" and evento is not None:
        grupos = []  # [{"rotulo", "titulos": [...]}] na ordem de aparição
        linhas = []
        minutos_total = 0
        for at in atividades_do_palestrante(evento, participante):
            rotulo = _rotulo_tipo(at)
            minutos = _minutos_efetivos(at, config)
            if minutos:
                minutos_total += minutos
            carga = _formatar_carga(minutos)
            data_txt = local_legivel(at.data_hora_inicio, "%d/%m/%Y")
            if carga:
                linhas.append(
                    f"- {rotulo}: {at.titulo}, com carga horária {carga} ({data_txt});"
                )
            else:
                linhas.append(f"- {rotulo}: {at.titulo} ({data_txt});")
            atividades.append({
                "titulo": at.titulo,
                "tipo": rotulo,
                "carga_horaria": carga,
                "carga_minutos": minutos or 0,
                "data": data_txt,
            })
            for grupo in grupos:
                if grupo["rotulo"] == rotulo:
                    grupo["titulos"].append(at.titulo)
                    break
            else:
                grupos.append({"rotulo": rotulo, "titulos": [at.titulo]})
        atividades_lista = "\n".join(linhas)
        atividades_resumo = ", ".join(
            f"{len(g['titulos'])}× {g['rotulo']}" for g in grupos
        )
        atividades_texto = _agrupar_texto(grupos)
        n_atividades_txt = str(len(atividades))
        if minutos_total:
            carga_horaria = _formatar_carga(minutos_total)
            carga_horaria_total_txt = carga_horaria

    if funcao:
        tipo_ctx = "funcao"
    elif atividade is not None:
        tipo_ctx = "atividade"
    else:
        tipo_ctx = "evento"

    contexto = {
        # Pessoa
        "nome": nome,
        "primeiro_nome": participante.first_name or "",
        "sobrenome": participante.last_name or "",
        "cpf": participante.cpf,
        "cpf_mascara": formatar_cpf(participante.cpf),
        "email": participante.email or "",
        "telefone": participante.telefone or "",
        "funcao": funcao_txt,
        # Evento (com aliases legados)
        "evento": evento_titulo,
        "evento_nome": evento_titulo,
        "evento_local": evento_local,
        "evento_data_inicio": evento_data_inicio,
        "evento_data_fim": evento_data_fim,
        "evento_periodo": evento_periodo,
        "evento_categoria": evento_categoria,
        "evento_descricao": evento_descricao,
        "evento_carga_horaria": evento_carga_horaria,
        "organizador": organizador,
        # Atividade (com aliases legados)
        "atividade": atividade_titulo,
        "atividade_nome": atividade_titulo,
        "tipo_atividade": tipo_atividade,
        "atividade_tipo": tipo_atividade,
        "atividade_local": atividade_local,
        "local": local,
        "atividade_data": atividade_data,
        "atividade_hora_inicio": atividade_hora_inicio,
        "atividade_hora_fim": atividade_hora_fim,
        "atividade_inicio": atividade_inicio,
        "atividade_fim": atividade_fim,
        "atividade_periodo": atividade_periodo,
        "atividade_descricao": atividade_descricao,
        "atividade_palestrantes": atividade_palestrantes,
        "carga_horaria": carga_horaria,
        # Atividades do palestrante (agregado; vazio nas demais funções)
        "carga_horaria_total": carga_horaria_total_txt,
        "n_atividades": n_atividades_txt,
        "atividades_lista": atividades_lista,
        "atividades_texto": atividades_texto,
        "atividades_resumo": atividades_resumo,
        "atividades": atividades,
        # Certificado (com alias legado de {{data}})
        "data": data_emissao,
        "data_emissao": data_emissao,
        "hora_emissao": hora_emissao,
        "percentual_participacao": percentual_participacao_txt,
        "percentual_minimo": percentual_minimo_txt,
        "qr_url": qr_url,
        "tipo": tipo_ctx,
    }
    contexto.update(_metadados_contexto(participante))
    return contexto


def substituir_variaveis(texto, contexto) -> str:
    """Troca `{{chave}}` pelo valor do contexto (chaves desconhecidas ficam)."""
    if not texto:
        return ""
    saida = texto
    for chave, valor in contexto.items():
        saida = saida.replace("{{" + chave + "}}", str(valor or ""))
    return saida


# ---------------------------------------------------------------------------
# Renderização (modo fundo)
# ---------------------------------------------------------------------------

_AZUL = HexColor("#1F4E79")
_CINZA = HexColor("#333333")
_LINHA = HexColor("#1F4E79")


def _quebrar(texto, fonte, tamanho, largura_max, c):
    """Quebra o texto em linhas que caibam em `largura_max`."""
    linhas = []
    for paragrafo in (texto or "").splitlines() or [""]:
        palavras = paragrafo.split()
        if not palavras:
            linhas.append("")
            continue
        atual = palavras[0]
        for palavra in palavras[1:]:
            teste = atual + " " + palavra
            if pdfmetrics.stringWidth(teste, fonte, tamanho) <= largura_max:
                atual = teste
            else:
                linhas.append(atual)
                atual = palavra
        linhas.append(atual)
    return linhas


def _desenhar_fundo(c, config, width, height):
    """Pinta o fundo: imagem enviada ou o padrão interno."""
    fundo = getattr(config, "layout_fundo", None)
    if fundo:
        try:
            c.drawImage(ImageReader(fundo.arquivo.path), 0, 0, width=width, height=height,
                        preserveAspectRatio=False, mask="auto")
            return
        except Exception:
            pass  # fundo inválido: cai no padrão
    # Padrão interno (sóbrio, sem depender de arquivo).
    c.setFillColor(HexColor("#FFFFFF"))
    c.rect(0, 0, width, height, fill=True, stroke=False)
    c.setStrokeColor(_LINHA)
    c.setLineWidth(4)
    c.rect(24, 24, width - 48, height - 48)


def _desenhar_qr(c, contexto, width):
    """QR de verificação no canto inferior direito (clicável)."""
    import qrcode

    url = contexto.get("qr_url") or ""
    if not url:
        return
    qr = qrcode.make(url)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    buffer.seek(0)

    lado = 120
    x = width - lado - 30
    y = 72
    c.drawImage(ImageReader(buffer), x, y, width=lado, height=lado, mask="auto")
    c.linkURL(url, (x, y, x + lado, y + lado), relative=0)


def _desenhar_url(c, contexto, width):
    """URL de confirmação em uma linha, abaixo do rodapé, clicável."""
    url = contexto.get("qr_url") or ""
    if not url:
        return
    c.setFont("Helvetica", 6)
    c.setFillColor(_CINZA)
    y = 56
    c.drawCentredString(width / 2, y, url)
    largura = pdfmetrics.stringWidth(url, "Helvetica", 6)
    c.linkURL(
        url,
        (width / 2 - largura / 2, y - 1, width / 2 + largura / 2, y + 6),
        relative=0,
    )


def _desenhar_assinaturas(c, assinaturas, width):
    assinaturas = list(assinaturas)
    if not assinaturas:
        return
    n = len(assinaturas)
    faixa = width / (n + 1)
    y_linha = 110
    for i, a in enumerate(assinaturas):
        x = faixa * (i + 1)
        if getattr(a, "imagem", None):
            try:
                c.drawImage(
                    ImageReader(a.imagem.path), x - 115, y_linha - 4,
                    width=230, height=70, mask="auto", preserveAspectRatio=True,
                )
            except Exception:
                pass
        c.setStrokeColor(_CINZA)
        c.setLineWidth(1)
        c.line(x - 110, y_linha, x + 110, y_linha)
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(_CINZA)
        c.drawCentredString(x, y_linha - 15, a.nome)
        if a.cargo:
            c.setFont("Helvetica", 9)
            c.drawCentredString(x, y_linha - 27, a.cargo)


def _render_fundo(contexto, config) -> bytes:
    """Gera o PDF do certificado no modo 'fundo'. Devolve os bytes."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    width, height = landscape(A4)

    _desenhar_fundo(c, config, width, height)

    # Título
    c.setFont("Helvetica-Bold", 30)
    c.setFillColor(_AZUL)
    c.drawCentredString(width / 2, height - 95, (config.titulo or "CERTIFICADO").upper())

    # Corpo (com variáveis substituídas), centralizado e quebrado
    corpo = substituir_variaveis(config.corpo or "", contexto)
    if not corpo.strip():
        corpo = (
            "Certificamos que {{nome}} participou de {{atividade}}{{evento}}.\n"
            "Carga horária: {{carga_horaria}}."
        )
        corpo = substituir_variaveis(corpo, contexto)
    linhas = _quebrar(corpo, "Helvetica", 15, width - 200, c)
    y = height - 150
    c.setFillColor(_CINZA)
    c.setFont("Helvetica", 15)
    for linha in linhas[:10]:
        c.drawCentredString(width / 2, y, linha)
        y -= 22

    # Rodapé
    if config.rodape:
        c.setFont("Helvetica-Oblique", 10)
        c.drawCentredString(width / 2, 72, config.rodape)

    # URL de confirmação abaixo do rodapé (uma linha, clicável).
    _desenhar_url(c, contexto, width)

    _desenhar_assinaturas(c, config.assinaturas.all() if config.pk else [], width)
    _desenhar_qr(c, contexto, width)

    c.showPage()
    c.save()
    return buffer.getvalue()


def _qr_png(contexto) -> bytes:
    import qrcode

    qr = qrcode.make(contexto.get("qr_url") or "")
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    return buffer.getvalue()


def _docx_para_pdf(docx_path, outdir):
    """Converte .docx em .pdf com o LibreOffice (headless)."""
    import os
    import subprocess

    try:
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", outdir, docx_path],
            check=True,
            capture_output=True,
            timeout=180,
        )
    except FileNotFoundError as erro:
        raise LibreOfficeIndisponivel(
            "O LibreOffice não está instalado neste servidor; ele é necessário "
            "para o layout em modelo .docx."
        ) from erro
    base = os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
    return os.path.join(outdir, base)


def render_docx(contexto, config) -> bytes:
    """Gera o PDF a partir do template .docx (docxtpl) + LibreOffice.

    Aceita TODAS as variáveis de texto do contexto (ver `VARIAVEIS_CERTIFICADO`),
    por exemplo `{{nome}}`, `{{evento}}`, `{{evento_periodo}}`, `{{atividade}}`,
    `{{atividade_periodo}}`, `{{carga_horaria}}`, `{{data}}`, `{{local}}`,
    `{{meta_<chave>}}`. Tags de imagem: `{{qr}}`, `{{assinatura1}}`,
    `{{assinatura2}}`. Tags de assinante: `{{assinante1}}`, `{{cargo_assinante1}}`.
    """
    import os
    import tempfile

    from docx.shared import Mm
    from docxtpl import DocxTemplate, InlineImage

    doc = DocxTemplate(config.template.arquivo.path)
    ctx = dict(contexto)
    ctx["qr"] = InlineImage(doc, io.BytesIO(_qr_png(contexto)), width=Mm(25))

    for i, assinatura in enumerate(config.assinaturas.all(), start=1):
        ctx[f"assinante{i}"] = assinatura.nome
        ctx[f"cargo_assinante{i}"] = assinatura.cargo
        if assinatura.imagem:
            ctx[f"assinatura{i}"] = InlineImage(
                doc, assinatura.imagem.path, height=Mm(12)
            )

    doc.render(ctx)

    with tempfile.TemporaryDirectory() as tmp:
        docx_path = os.path.join(tmp, "certificado.docx")
        doc.save(docx_path)
        pdf_path = _docx_para_pdf(docx_path, tmp)
        with open(pdf_path, "rb") as arquivo:
            return arquivo.read()


def render_pdf(contexto, config) -> bytes:
    """Despacha o render pelo modo escolhido (texto livre ou .docx).

    No modo .docx, se a conversão falhar, NÃO gera o layout antigo em silêncio:
    levanta `CertificadoLayoutError` para o organizador saber do problema.
    """
    from .models import ConfiguracaoCertificado

    modo = getattr(config, "modo_layout", ConfiguracaoCertificado.MODO_TEXTO)
    if modo == ConfiguracaoCertificado.MODO_DOCX and getattr(config, "template", None):
        try:
            return render_docx(contexto, config)
        except (
            LibreOfficeIndisponivel,
            FileNotFoundError,
            subprocess.CalledProcessError,
        ) as erro:
            logger.exception("certificados: falha ao gerar o modelo .docx")
            raise CertificadoLayoutError(
                "O certificado está configurado no modelo .docx, mas a conversão "
                "para PDF falhou. Verifique se o LibreOffice está instalado no "
                "servidor ou use o modo 'Texto livre'."
            ) from erro
    return _render_fundo(contexto, config)


def gerar_certificado(participante, *, atividade=None, evento=None, config=None, funcao=None):
    """Gera o PDF de um certificado e devolve um ContentFile pronto para salvar."""
    from django.core.files.base import ContentFile

    if evento is None and atividade is not None:
        evento = atividade.evento
    if config is None:
        config = config_efetiva(atividade, evento, funcao)

    contexto = contexto_certificado(
        participante, atividade=atividade, evento=evento, config=config, funcao=funcao
    )
    if config is not None:
        dados = render_pdf(contexto, config)
    else:
        dados = _render_padrao(contexto, atividade, evento, funcao)

    nome = f"certificado_{participante.id}.pdf"
    return ContentFile(dados, nome)


def _render_padrao(contexto, atividade, evento, funcao=None):
    """Fallback sem configuração: usa a config "virtual" só com o padrão."""
    from .models import ConfiguracaoCertificado

    if funcao:
        corpo = (
            "Certificamos que {{nome}} atuou como {{funcao}} no evento "
            "{{evento}}, realizado em {{local}}."
        )
    elif atividade is not None:
        corpo = (
            "Certificamos que {{nome}} participou da atividade {{atividade}}.\n"
            "Carga horária: {{carga_horaria}}."
        )
    else:
        corpo = (
            "Certificamos que {{nome}} participou do evento {{evento}}, "
            "realizado em {{local}}, com participação de "
            "{{percentual_participacao}}."
        )
    virtual = ConfiguracaoCertificado(
        titulo="CERTIFICADO DE PARTICIPAÇÃO",
        corpo=corpo,
    )
    return render_pdf(contexto, virtual)


# ---------------------------------------------------------------------------
# Emissão e entrega
# ---------------------------------------------------------------------------


def _enviar_email(certificado, config, evento):
    """Envia o certificado por e-mail (best-effort) quando configurado."""
    if config is None or not config.enviar_email:
        return
    participante = certificado.participante
    if not participante.email or not certificado.pdf:
        return

    from django.conf import settings
    from django.template.loader import render_to_string

    from . import emails

    try:
        certificado.pdf.open("rb")
        conteudo = certificado.pdf.read()
    except Exception:
        logger.exception("certificados: falha ao ler o PDF de %r", participante.email)
        return
    finally:
        try:
            certificado.pdf.close()
        except Exception:
            pass

    if certificado.atividade_id:
        escopo = f"atividade {certificado.atividade.titulo}"
    elif certificado.funcao:
        escopo = f"{certificado.get_funcao_display()} — evento {evento.title if evento else ''}"
    else:
        escopo = f"evento {evento.title if evento else ''}"
    corpo = render_to_string(
        "emails/certificado.txt",
        {
            "nome": participante.get_full_name(),
            "escopo": escopo,
            "site_url": emails.site_url(),
            "site_nome": getattr(settings, "SITE_NAME", "Nossos Eventos"),
        },
    )
    emails.enviar_com_anexo(
        f"Seu certificado — {escopo}",
        [participante.email],
        corpo,
        [("certificado.pdf", conteudo, "application/pdf")],
    )


def emitir(participante, *, atividade=None, evento=None, funcao=None):
    """Gera (uma única vez) o certificado de uma atividade, evento ou função.

    Idempotente: se já existir, devolve o existente sem gerar de novo nem
    reenviar e-mail. Devolve `(certificado, criado)`.
    """
    if evento is None and atividade is not None:
        evento = atividade.evento
    config = config_efetiva(atividade, evento, funcao)

    if funcao:
        tipo = Certificado.TIPO_FUNCAO
        evento_gravado = evento
        existente = Certificado.objects.filter(
            participante=participante,
            atividade__isnull=True,
            evento=evento,
            funcao=funcao,
        ).first()
    elif atividade is not None:
        tipo = Certificado.TIPO_ATIVIDADE
        evento_gravado = None
        existente = Certificado.objects.filter(
            participante=participante, atividade=atividade, evento__isnull=True
        ).first()
    else:
        tipo = Certificado.TIPO_EVENTO
        evento_gravado = evento
        existente = Certificado.objects.filter(
            participante=participante,
            evento=evento,
            atividade__isnull=True,
            funcao="",
        ).first()
    if existente is not None:
        _marcar_inscricao_emitida(participante, atividade)
        return existente, False

    arquivo = gerar_certificado(
        participante, atividade=atividade, evento=evento, config=config, funcao=funcao
    )
    certificado = Certificado.objects.create(
        participante=participante,
        atividade=atividade,
        evento=evento_gravado,
        tipo=tipo,
        funcao=funcao or "",
        carga_horaria=carga_horaria_efetiva(atividade, evento, config),
        config=config,
        pdf=arquivo,
    )
    _marcar_inscricao_emitida(participante, atividade)
    _enviar_email(certificado, config, evento)
    return certificado, True


def _marcar_inscricao_emitida(participante, atividade):
    """Mantém `Inscricao.certificado_emitido` em sincronia (é apenas um cache).

    A fonte de verdade é a tabela `Certificado`; a flag existe para telas e
    filtros antigos. É atualizada em TODO caminho de emissão — inclusive quando
    o certificado já existia — para não recriar divergência.
    """
    if atividade is None:
        return
    Inscricao.objects.filter(
        participante=participante, atividade=atividade
    ).update(certificado_emitido=True)
