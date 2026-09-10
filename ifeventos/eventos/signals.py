from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Inscricao 
from .models import Atividade
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





@receiver(post_save, sender=Atividade)
def atividade_salva(sender, instance, created, **kwargs):
    data = {
        "titulo": instance.titulo,
        "evento": instance.evento.title,
        "tipo": instance.tipo.nome,
        "id": instance.id,
        "n_vagas": instance.n_vagas,
        "n_inscricoes": instance.n_inscricoes,
        "data_hora_inicio": instance.data_hora_inicio.isoformat() if instance.data_hora_inicio else None,
        "data_hora_fim": instance.data_hora_fim.isoformat() if instance.data_hora_fim else None,
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
