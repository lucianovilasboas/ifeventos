import json
import openai
import datetime
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.utils.timezone import now
from asgiref.sync import sync_to_async
import socketio



client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

async def gerar_mensagem_para_usuario(tipo_usuario):
    """
    Gera uma mensagem personalizada para o usuário com base no seu tipo.
    """

    prompt = f"""Crie uma mensagem motivacional e informativa para um usuário do sistema de eventos. 
                O usuário é um {tipo_usuario}. A mensagem deve ser curta e inspiradora.
                Gere apenas uma frase.
                """
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=70
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Não foi possível gerar uma mensagem no momento. Erro: {str(e)}"



async def get_mensagem_do_dia(usuario, tipo_usuario):
    """
    Retorna a mensagem armazenada no cache ou gera uma nova se for um novo dia.
    Usa sync_to_async para chamadas síncronas de cache.
    """
    chave_cache = f"_{usuario}_{tipo_usuario}__ia_mensagem_do_dia"
    chave_data  = f"_{usuario}_{tipo_usuario}__ia_mensagem_data"

    # Converter chamadas síncronas do cache para assíncronas
    mensagem = await sync_to_async(cache.get)(chave_cache, None)
    ultima_data_str = await sync_to_async(cache.get)(chave_data, None)

    ultima_data = datetime.datetime.fromisoformat(ultima_data_str) if ultima_data_str else None

    # Se a mensagem não existe ou foi gerada em um dia anterior, gera uma nova
    if not mensagem or not ultima_data or ultima_data.date() < now().date():
        mensagem = await gerar_mensagem_para_usuario(tipo_usuario)
        await sync_to_async(cache.set)(chave_cache, mensagem, timeout=86400)  # Cache por 24h
        await sync_to_async(cache.set)(chave_data, now().isoformat(), timeout=86400) # Cache por 24h

    return mensagem



@csrf_exempt
@login_required
async def ia_mensagem_view(request):
    """
    View assíncrona que recebe um tipo de usuário via POST e retorna a mensagem gerada pela IA Openai.
    """
    if request.method == "POST":
        try:
            data = json.loads(request.body.decode("utf-8")) 
            tipo_usuario = data.get("tipo_usuario", "Organizador")
            usuario      = data.get("usuario", "Anônimo")
            mensagem = await get_mensagem_do_dia(usuario, tipo_usuario)
            return JsonResponse({"mensagem": mensagem})
        except Exception as e:
            return JsonResponse({"erro": str(e)}, status=500)
    else:
        return JsonResponse({"erro": "Método não permitido"}, status=405)



# -- Função para gerar descrição de evento --
# -- Adicionado por Luciano Vilas Boas --

async def gerar_descricao_evento(titulo, data_inicio, data_fim, local, tipo):
    """
    Usa a IA para gerar automaticamente uma descrição de evento baseada no título fornecido.
    """
    
    info = f"o(a) {tipo}: '{titulo}'." if tipo else f"o evento: '{titulo}'."
    local = f"Local: {local}." if local else ""
    
    prompt = f"""Crie uma descrição para {info} 
                 com início em {data_inicio} e término em {data_fim}. {local} 
                 A descrição deve ser atrativa e informativa, incentivando a participação.
                 Escreva apenas um parágrafo.
                 """

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            max_tokens = 120
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return "Não foi possível gerar uma descrição no momento. Tente novamente mais tarde."



@csrf_exempt
@login_required
async def gerar_conteudo_ajax(request):
    """
    View que recebe um título de evento e retorna uma descrição gerada automaticamente pela IA.
    """
    if request.method == "POST":
        data = json.loads(request.body)
        titulo = data.get("titulo", None)
        data_inicio = data.get("data_inicio", None)
        data_fim = data.get("data_fim", None)
        local = data.get("local", None)
        tipo = data.get("tipo", None)

        if not titulo:
            return JsonResponse({"error": "Título não pode estar vazio."}, status=400)

        descricao = await gerar_descricao_evento(titulo, data_inicio, data_fim, local, tipo)
        return JsonResponse({"descricao": descricao})

    return JsonResponse({"error": "Método inválido."}, status=400)




# -- Função para notificar eventos via SocketIO --
async def notify_socketio(event_type, data):
    sio = socketio.AsyncClient()
    try:
        # Endereço interno do servidor Socket.IO (mesmo contêiner, porta 8500).
        # Antes era um domínio DuckDNS fixo, que só funcionava na máquina antiga.
        await sio.connect(settings.SOCKET_INTERNAL_URL)
        await sio.emit(event_type, data)
        print(f"[SocketIO] Notificação enviada: {event_type} - {data}")
        await sio.disconnect()
    except Exception as e:
        print(f"[SocketIO] Falha ao conectar: {e}")


