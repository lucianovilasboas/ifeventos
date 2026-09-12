from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Inscricao 
from .models import Atividade
from .models import Presenca
from .services import notify_socketio
import asyncio


# Atualiza o número de inscrições sempre que uma nova inscrição é criada ou removida
@receiver(post_save, sender=Inscricao)
@receiver(post_delete, sender=Inscricao)
def atualizar_inscricoes(sender, instance, **kwargs):
    atividade = instance.atividade  # Obtém a atividade associada à inscrição
    atividade.inscricoes = Inscricao.objects.filter(atividade=atividade).count()

    atividade.save()  

    # Executa notificação com asyncio ou se falhar, em thread separada
    # para evitar problemas de loop de evento
    try:
        data = {
            "atividade_id": atividade.id,
            "n_inscricoes": atividade.inscricoes,
            "acao": "inscricao"
        }
        asyncio.run( notify_socketio("update_inscricao", data) )
        print(f"> try [SocketIO] Notificação enviada: update_inscricao - {atividade.id} - {atividade.inscricoes}")
    except RuntimeError:
        import threading
        threading.Thread( target=lambda: asyncio.run(notify_socketio("update_inscricao", data))).start()
        print(f"> except [SocketIO] Notificação enviada em thread: update_inscricao - {atividade.id} - {atividade.inscricoes}") 





def _iso(valor):
    """devolve a data em ISO, aceitando datetime/date ou string já pronta.

    O campo pode chegar aqui como string quando o objeto foi criado sem passar
    pelo formulário/serializer (o Django converte só na hora de gravar, e o
    atributo do instance continua str) — chamar .isoformat() direto estourava
    AttributeError.
    """
    if valor is None:
        return None
    isoformat = getattr(valor, "isoformat", None)
    return isoformat() if callable(isoformat) else str(valor)


@receiver(post_save, sender=Atividade)
def atividade_salva(sender, instance, created, **kwargs):
    data = {
        "titulo": instance.titulo,
        "evento": instance.evento.title if instance.evento_id else None,
        # `tipo` é opcional no model: sem o guarda, criar atividade sem tipo
        # estourava AttributeError ('NoneType' has no attribute 'nome') -> 500.
        "tipo": instance.tipo.nome if instance.tipo else None,
        "id": instance.id,
        "n_vagas": instance.n_vagas,
        "n_inscricoes": instance.n_inscricoes,
        "data_hora_inicio": _iso(instance.data_hora_inicio),
        "data_hora_fim": _iso(instance.data_hora_fim),
        "acao": "atividade",
    }

    
    tipo = "new_activity"  if created else "update_atividate"

    print(f"Tipo: {tipo}")
    print(f"Data: {data}")

    # Executa notificação com asyncio
    try:
        asyncio.run(notify_socketio(tipo, data))
        print(f"> try [SocketIO] Notificação enviada: {tipo} - {data}")
    except RuntimeError:
        # fallback em thread separada (caso use em contextos assíncronos)
        import threading
        threading.Thread(target=lambda: asyncio.run(notify_socketio(tipo, data))).start()
        print(f"> except [SocketIO] Notificação enviada em thread: {tipo} - {data}")



@receiver(post_delete, sender=Atividade)
def atividade_deletada(sender, instance, **kwargs):
    data = {
        "titulo": instance.titulo,
        "id": instance.id,
        "acao": "atividade",
    }

    # Executa notificação com asyncio
    try:
        asyncio.run(notify_socketio("delete_activity", data))
        print(f"> try [SocketIO] Notificação enviada: delete_activity - {data}")
    except RuntimeError:
        # fallback em thread separada (caso use em contextos assíncronos)
        import threading
        threading.Thread(target=lambda: asyncio.run(notify_socketio("delete_activity", data))).start()
        print(f"> except [SocketIO] Notificação enviada em thread: delete_activity - {data}")


@receiver(post_delete, sender=Inscricao)
def remover_presenca_da_inscricao(sender, instance, **kwargs):
    """Rede de segurança: inscrição removida não deixa presença para trás.

    O caminho normal é `eventos.inscricoes.cancelar_inscricao`, que cancela a
    presença COM auditoria e é o único que consegue recusar quando já existe
    certificado emitido. Este receiver cobre o que não passa por lá — o admin,
    um `queryset.delete()` em lote e qualquer código futuro. Quando o serviço já
    cancelou, aqui não encontra nada e não faz nada.

    Aqui a presença é apagada SEM auditoria, de propósito. Excluir uma
    atividade, um evento ou uma pessoa passa por este receiver em cascata:
    gravar auditoria nesse instante apontaria para o registro que está sendo
    apagado na MESMA transação — a chave estrangeira quebra e a exclusão morre.
    Auditoria é para ação de gente, e essas já são registradas em
    `cancelar_inscricao` e em `Presenca.cancelar`.
    """
    Presenca.objects.filter(
        participante=instance.participante, atividade=instance.atividade
    ).delete()


@receiver(post_delete, sender=Presenca)
def presenca_removida(sender, instance, **kwargs):
    """Avisa as telas abertas (QR da atividade, check-in) que a presença saiu.

    Sem isto a lista da outra tela só se corrige na próxima atualização
    periódica (10 s) — e quem está na porta vê um nome que já não vale.
    """
    data = {
        "presenca_id": instance.id,
        "atividade_id": instance.atividade_id,
        "acao": "presenca",
    }
    try:
        asyncio.run(notify_socketio("presenca_cancelada", data))
        print(f"> try [SocketIO] Notificação enviada: presenca_cancelada - {data}")
    except RuntimeError:
        import threading
        threading.Thread(
            target=lambda: asyncio.run(notify_socketio("presenca_cancelada", data))
        ).start()
        print(f"> except [SocketIO] Notificação enviada em thread: presenca_cancelada - {data}")
