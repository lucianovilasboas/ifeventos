import socketio
import uvicorn

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins="*")
app = socketio.ASGIApp(sio)

connected_users = {}  # {sid: user_data}

@sio.event
async def connect(sid, environ):
    print("🔌  Cliente conectado:", sid)


@sio.event
async def register_user(sid, data):
    connected_users[data['email']] = data
    print("✅ Usuário registrado:", data['email'])
    await sio.emit('update_user_list', list(connected_users.values()))


@sio.event
async def disconnect(sid):
    connected_users.pop(sid, None)
    print("⛔ Cliente desconectado:", sid)
    await sio.emit('update_user_list', list(connected_users.values()))


@sio.event
async def new_event(sid,data):
    print(f"[🔔] Novo evento recebido de {sid}: {data}")
    await sio.emit('event_created', data)


@sio.event
async def update_atividate(sid, data):
    print(f"[🔔] Atualização da atividade recebida de {sid}: {data}")
    # Aqui você pode fazer broadcast para os outros usuários, logar, etc.
    await sio.emit('atividate_update', data)


@sio.event
async def new_activity(sid, data):
    print(f"\n==>>> [🔔] Nova atividade recebida de {sid}: {data}")
    print(f"==>>> [🔔] enviada para atividade_created\n")
    await sio.emit('atividade_created', data)


@sio.event
async def delete_activity(sid, data):
    print(f"[🔔] Atividade deletada recebida de {sid}: {data}")
    await sio.emit('atividade_deleted', data)



@sio.event
async def update_inscricao(sid,data):
    print(f"\n=>> [🔔] Nova inscrição recebida de {sid}: {data}\n")
    await sio.emit('inscricao_atualizada', data)




@sio.event
async def notify_atividade_inicio(sid,data):
    print(f"[🔔] Notificação de início de atividade recebida de {sid}: {data}")
    await sio.emit('atividade_inicio_alert', data)


@sio.event
async def presenca_confirmada(sid, data):
    """Repassa o sinal de presença confirmada para quem está com a tela do QR aberta.

    O dado é anônimo de propósito (id da atividade, do evento e da presença):
    este servidor não tem autenticação nem salas, então nome de pessoa não
    trafega por aqui. Quem busca os detalhes é a tela do organizador, que está
    autenticada, pela API de presenças.
    """
    print(f"[🔔] Presença confirmada recebida de {sid}: {data}")
    await sio.emit('presenca_confirmada', data)


# if __name__ == "__main__":
#     uvicorn.run(app, host="0.0.0.0", port=8500)
