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


@register.filter
def nome_vinculo(participante):
    """Nome do participante com o vínculo (ver `metadados.nome_com_vinculo`).

    Uso: `{{ inscrito.participante|nome_vinculo }}`.
    """
    from eventos.metadados import nome_com_vinculo

    if participante is None:
        return ""
    return nome_com_vinculo(participante)
