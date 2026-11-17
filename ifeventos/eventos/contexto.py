"""Evento em foco nos painéis (participante e organizador).

O painel deixou de listar todos os eventos de uma vez: a pessoa fixa um
**evento padrão** e as atividades da tela passam a ser as daquele evento. Este
módulo é a fonte única da regra — ordenação dos grupos, escolha do padrão e
quem pode fixar o quê — para as duas telas não divergirem.

Encerrar é um ato explícito do organizador (`Evento.arquivado_em`). Passar da
data **não** arquiva: o evento fica em `a_encerrar` até alguém decidir. Por
isso os grupos são quatro:

- **atuais** (`data_inicio <= hoje <= data_fim`): o que começou por último
  primeiro; entre simultâneos, o mais atual aparece primeiro;
- **futuros** (`data_inicio > hoje`): o mais próximo primeiro;
- **a_encerrar** (`data_fim < hoje` e ainda aberto): o mais recente primeiro —
  é a fila de trabalho do organizador;
- **arquivados** (encerrados pelo organizador): o encerrado por último primeiro
  (arquivo, separado do fluxo).

Evento padrão = escolha salva, se não estiver arquivada; senão o primeiro atual;
senão o próximo futuro; senão o primeiro da fila `a_encerrar`. Arquivado nunca
vira padrão. Assim o padrão migra sozinho quando o evento termina, mas o antigo
só desce para "Eventos passados" quando o organizador encerra.
"""

from django.db.models import Count, Q
from django.utils import timezone

from .models import Evento

ATUAL = "atual"
PROXIMO = "proximo"
TERMINADO = "terminado"
ARQUIVADO = "arquivado"

ROTULOS = {
    ATUAL: "Atual",
    PROXIMO: "Próximo",
    TERMINADO: "Terminado",
    ARQUIVADO: "Encerrado",
}


def _marcar(evento, situacao):
    """Anota o grupo no próprio objeto (o template mostra o selo sem if-chains)."""
    evento.situacao_contexto = situacao
    evento.situacao_contexto_rotulo = ROTULOS[situacao]
    return evento


def classificar(eventos, hoje=None):
    """Divide os eventos em atuais, futuros, a_encerrar e arquivados.

    Aceita queryset ou lista. A ordem é estável e independe da ordem de entrada,
    porque cada grupo tem sua própria chave (data + id como desempate).
    """
    hoje = hoje or timezone.localdate()
    atuais, futuros, a_encerrar, arquivados = [], [], [], []
    for evento in eventos:
        if getattr(evento, "arquivado_em", None) is not None:
            arquivados.append(evento)
        elif evento.data_fim < hoje:
            a_encerrar.append(evento)
        elif evento.data_inicio > hoje:
            futuros.append(evento)
        else:
            atuais.append(evento)

    # Entre simultâneos, o que começou por último (o "mais atual") primeiro.
    atuais.sort(key=lambda e: (e.data_inicio, e.id), reverse=True)
    futuros.sort(key=lambda e: (e.data_inicio, e.id))
    a_encerrar.sort(key=lambda e: (e.data_fim, e.id), reverse=True)
    arquivados.sort(key=lambda e: (e.arquivado_em, e.id), reverse=True)

    for evento in atuais:
        _marcar(evento, ATUAL)
    for evento in futuros:
        _marcar(evento, PROXIMO)
    for evento in a_encerrar:
        _marcar(evento, TERMINADO)
    for evento in arquivados:
        _marcar(evento, ARQUIVADO)

    return {
        "atuais": atuais,
        "futuros": futuros,
        "a_encerrar": a_encerrar,
        "arquivados": arquivados,
    }


def resolver_padrao(usuario, grupos):
    """Qual evento fica em foco: a escolha salva ou a regra automática.

    Devolve sempre o objeto que está nos grupos (já com o selo/situação), não a
    instância carregada pela FK — assim o template não precisa de outro acesso
    ao banco nem de um caso especial.
    """
    salvo = getattr(usuario, "evento_padrao", None)
    if salvo is not None:
        # A escolha vale enquanto o evento não for arquivado; depois ele vira
        # arquivo e o foco passa para o evento de agora/da vez.
        for evento in grupos["atuais"] + grupos["futuros"] + grupos["a_encerrar"]:
            if evento.id == salvo.id:
                return evento

    for grupo in ("atuais", "futuros", "a_encerrar"):
        if grupos[grupo]:
            return grupos[grupo][0]
    return None


# ---------------------------------------------------------------------------
# Universo de eventos de cada visão
# ---------------------------------------------------------------------------

def eventos_do_participante(usuario):
    """Eventos que o participante pode acompanhar.

    Todo evento com atividade publicada (é o que a tela de inscrição oferece)
    mais os eventos em que ele já tem inscrição — inclusive os arquivados, que
    aparecem no arquivo com as presenças/certificados.
    """
    return (
        Evento.objects.filter(
            Q(atividades__publicada=True)
            | Q(atividades__inscritos__participante=usuario)
        )
        .annotate(
            n_atividades=Count(
                "atividades", filter=Q(atividades__publicada=True), distinct=True
            )
        )
        .distinct()
    )


def eventos_do_organizador(usuario):
    """Eventos que a pessoa gerencia (dono ou co-organizador)."""
    if usuario.is_superuser:
        return Evento.objects.all()
    return Evento.objects.filter(
        Q(organizador=usuario) | Q(organizadores=usuario)
    ).distinct()


def eventos_do_usuario(usuario):
    """União das duas visões — o que a pessoa pode fixar como padrão."""
    if usuario.is_superuser:
        return Evento.objects.all()
    return Evento.objects.filter(
        Q(organizador=usuario)
        | Q(organizadores=usuario)
        | Q(atividades__publicada=True)
        | Q(atividades__inscritos__participante=usuario)
    ).distinct()


def pode_fixar(usuario, evento):
    """A pessoa enxerga este evento em algum dos painéis?"""
    return eventos_do_usuario(usuario).filter(pk=evento.pk).exists()
