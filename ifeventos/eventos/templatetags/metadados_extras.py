"""Filtros para exibir os metadados configuráveis do participante."""

from django import template

register = template.Library()


@register.filter
def meta(dados, chave):
    """Valor de `dados[chave]` no dicionário de metadados (ou string vazia).

    Permite colunas dinâmicas nos relatórios:
        {{ inscrito.participante.metadados.dados|meta:coluna.chave }}
    """
    if isinstance(dados, dict):
        return dados.get(chave, "")
    return ""
