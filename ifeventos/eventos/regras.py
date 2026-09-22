"""Regras de visibilidade compartilhadas entre a API e o site.

Um único ponto para o que é "catálogo público": a listagem de atividades
(`AtividadeViewSet`) e o detalhe do evento (`EventoSerializer.atividades`)
precisam contar a MESMA história — foi a divergência entre elas que expôs
rascunho/proposta pendente no detalhe do evento.
"""


def atividades_publicas(qs):
    """Atividades visíveis ao público: apenas as publicadas."""
    return qs.filter(publicada=True)
