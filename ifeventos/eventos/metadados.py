"""Metadados configuráveis do participante (matrícula, curso, turma, ano…).

Os campos são definidos por escola em `settings.METADADOS_PARTICIPANTE` — nunca
em colunas fixas no banco. Os valores ficam em `ParticipanteMetadados.dados`
(JSON), chaveados pela `chave` do campo. Este módulo centraliza a leitura da
configuração e a montagem/validação dos campos, para que formulários,
relatórios e exportações contem a mesma história.
"""

import re

from django import forms
from django.conf import settings

TIPOS_VALIDOS = {"texto", "numero", "escolha"}
_NUMERO = re.compile(r"^\d+([.,]\d+)?$")


def _normalizar(item):
    chave = (item.get("chave") or "").strip()
    if not chave:
        return None
    tipo = item.get("tipo") if item.get("tipo") in TIPOS_VALIDOS else "texto"

    # Visibilidade condicional: só vale com chave e valores válidos.
    visivel_quando = None
    condicao = item.get("visivel_quando") or {}
    if condicao.get("chave") and condicao.get("valores"):
        visivel_quando = {
            "chave": str(condicao["chave"]).strip(),
            "valores": [str(v) for v in condicao["valores"]],
        }

    opcoes_por = {
        str(k): [str(v) for v in (lista or [])]
        for k, lista in (item.get("opcoes_por") or {}).items()
    }

    return {
        "chave": chave,
        "rotulo": item.get("rotulo") or chave.replace("_", " ").title(),
        "tipo": tipo,
        "obrigatorio": bool(item.get("obrigatorio", False)),
        "opcoes": [str(o) for o in (item.get("opcoes") or [])],
        "opcoes_por": opcoes_por,
        "depende_de": (item.get("depende_de") or "").strip() or None,
        "visivel_quando": visivel_quando,
        "ajuda": item.get("ajuda") or "",
        "ordem": item.get("ordem", 0),
    }


def campos():
    """Lista normalizada dos campos configurados, na ordem definida (`ordem`)."""
    config = getattr(settings, "METADADOS_PARTICIPANTE", []) or []
    lista = [c for c in (_normalizar(item) for item in config) if c]
    lista.sort(key=lambda c: c["ordem"])
    return lista


def opcoes_do_campo(campo, valor_pai=None):
    """Opções válidas do campo (dependentes do valor do campo pai, se houver)."""
    if campo["depende_de"]:
        return list(campo["opcoes_por"].get(valor_pai or "", []))
    return list(campo["opcoes"])


def visivel(campo, valores):
    """O campo está visível dado o dicionário de valores dos outros campos?"""
    condicao = campo["visivel_quando"]
    if not condicao:
        return True
    return valores.get(condicao["chave"]) in condicao["valores"]


def valores_meta(cleaned_data):
    """Valores atuais dos campos de metadados (chave -> texto), do formulário."""
    valores = {}
    for campo in campos():
        valor = cleaned_data.get(nome_do_campo(campo["chave"]))
        valores[campo["chave"]] = "" if valor is None else str(valor).strip()
    return valores


def construir_field(campo, valor_pai=None):
    """Campo de formulário correspondente à definição (nome prefixado com meta_).

    Nenhum campo nasce `required` no HTML: a obrigatoriedade é cobrada no
    `clean()` do formulário (`validar`) — fonte única da verdade. Sem isso o
    erro "Este campo é obrigatório." aparecia DUAS vezes (no campo e na
    validação), e um `required` num campo escondido travaria o envio.
    """
    comum = {
        "label": campo["rotulo"],
        "required": False,
        "help_text": campo["ajuda"],
    }
    if campo["tipo"] == "numero":
        return forms.CharField(
            widget=forms.NumberInput(attrs={"class": "form-control"}), **comum
        )
    if campo["tipo"] == "escolha":
        escolhas = [("", "Selecione…")] + [
            (o, o) for o in opcoes_do_campo(campo, valor_pai)
        ]
        return forms.ChoiceField(
            choices=escolhas, widget=forms.Select(attrs={"class": "form-control"}), **comum
        )
    return forms.CharField(
        max_length=255, widget=forms.TextInput(attrs={"class": "form-control"}), **comum
    )


def nome_do_campo(chave):
    """Nome do campo no formulário (evita colisão com campos do model)."""
    return f"meta_{chave}"


def coletar(cleaned_data):
    """Extrai só as chaves VISÍVEIS e preenchidas, com os valores como texto.

    Campos ocultos (fora da condição de visibilidade) são descartados — assim
    trocar o vínculo não deixa dados antigos grudados no JSON.
    """
    valores = valores_meta(cleaned_data)
    dados = {}
    for campo in campos():
        if not visivel(campo, valores):
            continue
        valor = valores.get(campo["chave"])
        if valor:
            dados[campo["chave"]] = valor
    return dados


def _normalizar_valores(valores):
    """Só as chaves configuradas, como texto sem espaços nas pontas."""
    return {
        campo["chave"]: ("" if valores.get(campo["chave"]) is None
                          else str(valores.get(campo["chave"])).strip())
        for campo in campos()
    }


def _erros_do_campo(campo, valor, valores):
    if campo["obrigatorio"] and not valor:
        return ["Este campo é obrigatório."]
    if not valor:
        return []
    if campo["tipo"] == "escolha":
        pai = valores.get(campo["depende_de"]) if campo["depende_de"] else None
        if valor not in opcoes_do_campo(campo, pai):
            return [f"'{valor}' não é um valor válido."]
    elif campo["tipo"] == "numero" and not _NUMERO.match(valor):
        return [f"'{valor}' não é um número."]
    return []


def validar(valores):
    """Valida os metadados e devolve `{chave: [mensagens]}` (só campos visíveis).

    Fonte única da verdade: o formulário, a importação por CSV e a API usam
    esta mesma validação.
    """
    valores = _normalizar_valores(valores)
    erros = {}
    for campo in campos():
        if not visivel(campo, valores):
            continue
        mensagens = _erros_do_campo(campo, valores[campo["chave"]], valores)
        if mensagens:
            erros[campo["chave"]] = mensagens
    return erros


def limpar(valores):
    """Devolve `(dados_visiveis, erros)`: o que gravar e o que está errado.

    Campos ocultos (fora da condição de visibilidade) são descartados; campos
    visíveis e vazios não entram.
    """
    valores = _normalizar_valores(valores)
    erros = validar(valores)
    dados = {}
    for campo in campos():
        if not visivel(campo, valores):
            continue
        if valores[campo["chave"]]:
            dados[campo["chave"]] = valores[campo["chave"]]
    return dados, erros


def colunas_selecionadas(query_params):
    """Colunas de metadados escolhidas na URL, na ordem da configuração.

    Sem `campos` na querystring => todos os campos ativos. Com `campos` (mesmo
    vazio) => só as chaves listadas — assim dá para escolher "nenhuma coluna".
    """
    todos = campos()
    if "campos" not in query_params:
        return todos
    escolhidas = {v for v in query_params.getlist("campos") if v}
    return [c for c in todos if c["chave"] in escolhidas]


def dados_de(participante):
    """Dicionário de metadados já salvos do participante (vazio se não houver)."""
    from .models import ParticipanteMetadados

    if participante is None or not getattr(participante, "pk", None):
        return {}
    obj = ParticipanteMetadados.objects.filter(participante_id=participante.pk).first()
    return dict(obj.dados) if obj else {}


def salvar(participante, dados):
    """Grava (cria/atualiza) os metadados do participante."""
    from .models import ParticipanteMetadados

    obj, _ = ParticipanteMetadados.objects.get_or_create(participante=participante)
    obj.dados = dados
    obj.save()
    return obj
