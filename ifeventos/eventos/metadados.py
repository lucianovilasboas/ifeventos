"""Metadados configuráveis do participante (matrícula, curso, turma, ano…).

Os campos são definidos por escola em `settings.METADADOS_PARTICIPANTE` — nunca
em colunas fixas no banco. Os valores ficam em `ParticipanteMetadados.dados`
(JSON), chaveados pela `chave` do campo. Este módulo centraliza a leitura da
configuração e a montagem/validação dos campos, para que formulários,
relatórios e exportações contem a mesma história.
"""

from django import forms
from django.conf import settings

TIPOS_VALIDOS = {"texto", "numero", "escolha"}


def _normalizar(item):
    chave = (item.get("chave") or "").strip()
    if not chave:
        return None
    tipo = item.get("tipo") if item.get("tipo") in TIPOS_VALIDOS else "texto"
    return {
        "chave": chave,
        "rotulo": item.get("rotulo") or chave.replace("_", " ").title(),
        "tipo": tipo,
        "obrigatorio": bool(item.get("obrigatorio", False)),
        "opcoes": [str(o) for o in (item.get("opcoes") or [])],
        "ajuda": item.get("ajuda") or "",
        "ordem": item.get("ordem", 0),
    }


def campos():
    """Lista normalizada dos campos configurados, na ordem definida (`ordem`)."""
    config = getattr(settings, "METADADOS_PARTICIPANTE", []) or []
    lista = [c for c in (_normalizar(item) for item in config) if c]
    lista.sort(key=lambda c: c["ordem"])
    return lista


def construir_field(campo):
    """Campo de formulário correspondente à definição (nome prefixado com meta_)."""
    comum = {
        "label": campo["rotulo"],
        "required": campo["obrigatorio"],
        "help_text": campo["ajuda"],
    }
    if campo["tipo"] == "numero":
        return forms.CharField(
            widget=forms.NumberInput(attrs={"class": "form-control"}), **comum
        )
    if campo["tipo"] == "escolha":
        escolhas = [("", "Selecione…")] + [(o, o) for o in campo["opcoes"]]
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
    """Extrai do formulário só as chaves configuradas, com os valores como texto."""
    dados = {}
    for campo in campos():
        valor = cleaned_data.get(nome_do_campo(campo["chave"]))
        if valor is None or str(valor).strip() == "":
            continue
        dados[campo["chave"]] = str(valor).strip()
    return dados


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
