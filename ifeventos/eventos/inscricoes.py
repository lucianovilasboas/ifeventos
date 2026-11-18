"""Regras de negócio de inscrição — inscrição e presença andam juntas.

Uma pessoa que sai da inscrição de uma atividade não deve continuar aparecendo
como presente nela: a lista de presença (relatórios) lê a INSCRIÇÃO confirmada,
enquanto a tela do QR e o check-in leem a PRESENÇA — sem esta regra, as duas
contam histórias diferentes sobre o mesmo fato.

Por que num módulo separado, e não na view: existem três caminhos que removem
inscrição (tela do participante, AJAX dela e API/MCP). Todos passam por aqui.
"""

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import Atividade, Certificado, Presenca


class InscricaoBloqueada(ValidationError):
    """Remoção de inscrição recusada por regra de negócio."""


def evento_encerrado(evento, hoje=None):
    """O evento já não aceita (des)inscrições de participantes?

    Vale a data final (`Evento.terminou`) **ou** o encerramento explícito do
    organizador (`Evento.arquivado`). Não confundir com "evento fora do painel":
    um evento vencido e ainda aberto continua visível ao organizador.
    """
    if evento is None:
        return True
    fim = evento.data_fim
    if isinstance(fim, str):        # instâncias recém-criadas em testes/fixtures
        fim = parse_date(fim)
    if fim is None:
        return evento.arquivado_em is not None
    return bool(
        evento.arquivado_em is not None
        or fim < (hoje or timezone.localdate())
    )


def atividade_encerrada(atividade):
    """A atividade já terminou? (mesma regra de `Atividade.encerrada`)."""
    return bool(atividade.encerrada)


def motivo_inscricao_encerrada(atividade):
    """Motivo pelo qual o participante não pode se inscrever, ou None."""
    if evento_encerrado(atividade.evento):
        return "As inscrições deste evento estão encerradas."
    if atividade_encerrada(atividade):
        return "As inscrições para esta atividade estão encerradas."
    return None


def exigir_cancelamento_permitido(inscricao, por=None, hoje=None):
    """Participante não cancela depois que o evento termina.

    Organizador do evento, co-organizador e staff continuam podendo (pelo
    admin). O cancelamento em si segue a cargo de `cancelar_inscricao`; esta
    função é a trava de autorização usada nas entradas (tela, AJAX e API).
    """
    evento = inscricao.atividade.evento
    if not evento_encerrado(evento, hoje):
        return
    if por is not None:
        # Import local: crachas importa models, não este módulo, mas a função é
        # de autorização e não precisa entrar no topo (evita ciclo futuro).
        from .crachas import pode_gerenciar_evento

        if pode_gerenciar_evento(por, evento):
            return
    raise InscricaoBloqueada(
        "O evento já terminou; o cancelamento só pode ser feito pelo organizador."
    )


def conflito_com_inscricoes(participante, atividade):
    """Atividade já inscrita que choca de horário com esta (ou None).

    Usada tanto para RECUSAR a inscrição (view/AJAX/API) quanto para AVISAR
    antes, nas listas do participante. Devolve a primeira atividade conflitante,
    na ordem de horário.
    """
    inscritas = Atividade.objects.filter(
        inscritos__participante=participante
    ).exclude(pk=atividade.pk)
    for inscrita in inscritas.order_by("data_hora_inicio", "id"):
        if (
            atividade.data_hora_inicio < inscrita.data_hora_fim
            and atividade.data_hora_fim > inscrita.data_hora_inicio
        ):
            return inscrita
    return None


def certificados_que_dependem(participante, atividade):
    """Certificados que DEPENDEM da presença nesta atividade (queryset).

    São só dois: o certificado **da atividade** e o certificado **do evento**
    (`funcao=""`). Certificados de **função** (organizador/palestrante/equipe/
    comissão) vêm do vínculo com o evento, não da presença — por isso NÃO entram
    aqui (não devem bloquear nem ser removidos ao mexer na presença).
    """
    if atividade is None:
        return Certificado.objects.none()
    return Certificado.objects.filter(
        Q(participante=participante, atividade=atividade)
        | Q(
            participante=participante,
            atividade__isnull=True,
            evento=atividade.evento_id,
            funcao="",
        )
    )


def certificado_emitido(participante, atividade):
    """Certificado já emitido que DEPENDE desta presença (ou None).

    Considera os dois tipos: o certificado da atividade e o do evento. O de
    evento é emitido contando as atividades confirmadas da pessoa
    (`organizador/views.py`), então remover a presença também tiraria o lastro
    dele. Sem esta checagem, apagar a presença deixaria um certificado emitido
    sem nenhuma comprovação por trás.

    Certificados de **função** (organizador/palestrante/equipe/comissão) NÃO
    entram: eles vêm do vínculo com o evento, não da presença.
    """
    return certificados_que_dependem(participante, atividade).first()


def cancelar_inscricao(inscricao, por=None, motivo="Cancelamento de inscrição"):
    """Remove a inscrição e, junto, a presença da pessoa naquela atividade.

    Levanta `InscricaoBloqueada` quando já existe certificado emitido — nesse
    caso nada é alterado e quem chamou decide o que mostrar. O bloqueio é feito
    ANTES de apagar porque um signal de `post_delete` já não teria como recusar.

    Devolve o registro de auditoria do cancelamento da presença, ou None se não
    havia presença.
    """
    bloqueio = certificado_emitido(inscricao.participante, inscricao.atividade)
    if bloqueio is not None:
        raise InscricaoBloqueada(
            "Esta pessoa já tem certificado emitido "
            f"({bloqueio.atividade.titulo if bloqueio.atividade_id else bloqueio.evento.title}). "
            "Cancele o certificado antes de remover a inscrição."
        )

    # A presença sai primeiro: depois da inscrição apagada, o cancelamento
    # ainda funciona, mas perdemos a referência de qual atividade era.
    registro = None
    presenca = Presenca.objects.filter(
        participante=inscricao.participante, atividade=inscricao.atividade
    ).first()
    if presenca is not None:
        registro = presenca.cancelar(por=por, motivo=motivo)

    inscricao.delete()
    return registro
