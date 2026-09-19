"""Copiloto de criação de evento (planejamento da programação).

A partir de um resumo curto (tema, público, observações), o copiloto propõe:
- a **descrição** e a **categoria** do evento;
- **blocos** de horário;
- uma **programação inicial** (atividades com título, resumo, tipo e turno).

O organizador revisa; a programação sugerida pode ser aplicada ao evento como
**rascunhos** (reusa `importacao_programacao.importar_linhas`, mantendo a
idempotência por título + início). Sem IA, cai num plano básico determinístico.
"""

import re
from datetime import timedelta

from django.conf import settings
from asgiref.sync import sync_to_async

from . import importacao_assistida
from . import services
from . import contexto_ia
from .models import TipoAtividade, sem_acento

MODELO = settings.IA_MODELO_CLASSIFICACAO

# Tetos para não deixar o modelo (ou o usuário) criar um plano gigante.
MAX_ATIVIDADES = 8
MAX_BLOCOS = 6

# Blocos de horário padrão (fallback e validação).
BLOCOS_PADRAO = ["08:00-10:00", "10:00-12:00", "13:30-15:30", "15:30-17:30"]

TURNOS_VALIDOS = {"manha": "manha", "tarde": "tarde", "noite": "noite"}

_MAPA_TURNO = {
    "manha": "manha", "matutino": "manha", "morning": "manha",
    "tarde": "tarde", "vespertino": "tarde",
    "noite": "noite", "noturno": "noite",
}


def _limpar_nome(valor, limite=120):
    texto = " ".join(str(valor or "").split())
    texto = texto.strip(' .,;:-–—"\'')
    return texto[:limite]


def normalizar_turno(valor):
    return _MAPA_TURNO.get(sem_acento(valor).strip(), "")


def quantos_dias(evento):
    total = (evento.data_fim - evento.data_inicio).days
    return max(1, total + 1)


def _prompt(titulo, descricao, categoria, evento, observacoes, dossie_texto, tipos):
    return """Você é o copiloto de um organizador de eventos de um campus do IFMG.
Use como VERDADE o contexto do banco de dados abaixo (tipos, espaços, campos e
convenções da escola): proponha a programação reaproveitando o que já existe.

=== CONTEXTO DO BANCO ===
{dossie}
=== FIM DO CONTEXTO ===

Título do evento: {titulo}
Categoria/tema informada: {categoria}
Local: {local}
Período: {inicio} a {fim} ({dias} dia(s))
Descrição atual: {descricao}
Observações do organizador: {observacoes}

Monte um plano inicial. Regras:
1. "descricao": um parágrafo atrativo, em português, convidando a participar.
2. "categoria": um tema curto (1 a 3 palavras). Reuse a categoria informada quando fizer sentido.
3. "blocos": até {max_blocos} blocos no formato "HH:MM-HH:MM".
4. "atividades": até {max_atividades} atividades. Cada uma com "titulo", "descricao"
   curta, "tipo" (prefira um tipo do catálogo), "turno" ("manhã", "tarde" ou "noite"),
   "local" (prefira um espaço do catálogo) e "n_vagas" (inteiro; considere a capacidade).
5. Não invente datas exatas; use só o turno.

Responda SOMENTE com JSON neste formato:
{{"descricao": "...", "categoria": "...", "blocos": ["08:00-10:00"],
  "atividades": [{{"titulo": "...", "descricao": "...", "tipo": "...",
                   "turno": "manhã", "local": "...", "n_vagas": 30}}]}}""".format(
        dossie=dossie_texto,
        titulo=titulo or "(sem título)",
        categoria=categoria or "(não informada)",
        local=evento.local or "(não informado)",
        inicio=evento.data_inicio.strftime("%d/%m/%Y"),
        fim=evento.data_fim.strftime("%d/%m/%Y"),
        dias=quantos_dias(evento),
        descricao=descricao or "(sem descrição)",
        observacoes=observacoes or "(nenhuma)",
        max_blocos=MAX_BLOCOS,
        max_atividades=MAX_ATIVIDADES,
    )


def sanitizar_plano(dados, evento, tipos):
    """Valida/sanitiza o plano vindo da IA."""
    dados = dados if isinstance(dados, dict) else {}

    descricao = " ".join(str(dados.get("descricao") or "").split())[:1200]
    categoria = services.limpar_nome_categoria(dados.get("categoria"))

    blocos, vistas = [], set()
    for item in dados.get("blocos") or []:
        texto = str(item or "").strip()
        if re.match(r"^\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}$", texto) and texto not in vistas:
            vistas.add(texto)
            blocos.append(texto)
        if len(blocos) >= MAX_BLOCOS:
            break

    nomes_tipos = {sem_acento(t.nome): t.nome for t in tipos}
    atividades = []
    for item in dados.get("atividades") or []:
        if not isinstance(item, dict):
            continue
        titulo = _limpar_nome(item.get("titulo"))
        if not titulo:
            continue
        tipo = _limpar_nome(item.get("tipo"), 80)
        canonico = nomes_tipos.get(sem_acento(tipo))
        try:
            n_vagas = max(0, int(item.get("n_vagas")))
        except (TypeError, ValueError):
            n_vagas = 0
        atividades.append({
            "titulo": titulo,
            "descricao": " ".join(str(item.get("descricao") or "").split())[:400],
            "tipo": canonico or tipo,
            "turno": normalizar_turno(item.get("turno")) or "manha",
            "local": _limpar_nome(item.get("local"), 160),
            "n_vagas": n_vagas,
        })
        if len(atividades) >= MAX_ATIVIDADES:
            break

    return {
        "descricao": descricao,
        "categoria": categoria,
        "blocos": blocos,
        "atividades": atividades,
    }


def plano_basico(titulo, descricao, categoria, evento, tipos):
    """Plano determinístico para quando a IA não está disponível."""
    nomes = [t.nome for t in tipos]
    categoria_sugerida = services.sugerir_categoria_por_palavras(
        titulo, descricao, [valor for valor, _ in services.CATEGORIA_PALAVRAS.items()]
    )
    rotulos = dict(getattr(evento, "CATEGORIA_CHOICES", []))
    rotulo = rotulos.get(categoria_sugerida, categoria_sugerida) if categoria_sugerida else ""
    return {
        "descricao": "",
        "categoria": categoria or rotulo,
        "blocos": list(BLOCOS_PADRAO[:MAX_BLOCOS]),
        "atividades": [],
        "tipos_conhecidos": nomes,
    }


async def gerar_plano(titulo, descricao, categoria, evento, observacoes=""):
    """Gera o plano do evento (IA) com fallback determinístico.

    Devolve `{"descricao", "categoria", "blocos", "atividades", "origem", "aviso"}`.
    """
    tipos = await sync_to_async(list)(TipoAtividade.objects.order_by("nome"))
    dados_dossie = await sync_to_async(contexto_ia.dossie)(evento)
    dossie_texto = contexto_ia.resumo_texto(dados_dossie)
    try:
        client = services.get_openai_client()
        resposta = await client.chat.completions.create(
            model=MODELO,
            messages=[{"role": "system", "content": _prompt(
                titulo, descricao, categoria, evento, observacoes, dossie_texto, tipos
            )}],
            max_tokens=1500,
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        services.registrar_uso_ia("copiloto_evento", MODELO, resposta)
        import json as _json

        dados = _json.loads(resposta.choices[0].message.content or "{}")
        plano = sanitizar_plano(dados, evento, tipos)
        plano["origem"] = "ia"
        plano["aviso"] = "" if plano["atividades"] else "A IA não sugeriu atividades; monte a grade manualmente."
        return plano
    except Exception as erro:  # noqa: BLE001 - IA é acessória
        plano = plano_basico(titulo, descricao, categoria, evento, tipos)
        plano["origem"] = "heuristica"
        plano["aviso"] = "A IA não está disponível agora; usei um plano básico (%s)." % erro
        return plano


# ---------------------------------------------------------------------------
# Aplicar o plano: converter em linhas canônicas e importar como rascunho
# ---------------------------------------------------------------------------

def _tipo_existente(nome):
    nome = (nome or "").strip()
    if not nome:
        return None
    return TipoAtividade.objects.filter(nome__iexact=nome).first()


def plano_para_linhas(plano, evento):
    """Converte as atividades sugeridas em linhas canônicas da importação.

    O dia é distribuído a partir da data de início do evento (1-based) e o
    horário sai do turno (mesma tabela da importação assistida).
    """
    linhas = []
    total_dias = quantos_dias(evento)
    dados = contexto_ia.dossie(evento)
    nomes_locais = {sem_acento(n): n for n in dados.get("locais_conhecidos", [])}
    nomes_locais.update({sem_acento(e["nome"]): e["nome"] for e in dados.get("espacos", [])})
    for indice, atividade in enumerate(plano.get("atividades") or []):
        titulo = _limpar_nome(atividade.get("titulo"))
        if not titulo:
            continue
        dia = evento.data_inicio + timedelta(days=indice % total_dias)
        limites = importacao_assistida.TURNOS.get(
            atividade.get("turno", "manha"), importacao_assistida.TURNOS["manha"]
        )
        inicio = "%s %s" % (dia.strftime("%d/%m/%Y"), limites[0])
        fim = "%s %s" % (dia.strftime("%d/%m/%Y"), limites[1])
        tipo = _tipo_existente(atividade.get("tipo"))
        local_sugerido = _limpar_nome(atividade.get("local"), 160)
        local = nomes_locais.get(sem_acento(local_sugerido), local_sugerido)
        linhas.append({
            "titulo": titulo,
            "descricao": atividade.get("descricao", ""),
            "tipo": tipo.nome if tipo else "",
            "local": local,
            "inicio": inicio,
            "fim": fim,
            "n_vagas": str(atividade.get("n_vagas") or ""),
            "emite_certificado": "",
            "palestrantes": "",
        })
    return linhas
