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

from .models import Atividade, Certificado, Presenca


class InscricaoBloqueada(ValidationError):
    """Remoção de inscrição recusada por regra de negócio."""


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
