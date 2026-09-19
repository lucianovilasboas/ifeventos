import json
import logging
import re
import threading
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

from .models import sem_acento
from . import ia_config


logger = logging.getLogger("eventos.ia")


def registrar_uso_ia(operacao, modelo, resposta):
    """Registra uma chamada de IA (modelo e tokens) para custo/auditoria.

    Nunca levanta exceção: log é acessório e não pode derrubar a operação.
    """
    try:
        uso = getattr(resposta, "usage", None)
        logger.info(
            "ia operacao=%s modelo=%s tokens_prompt=%s tokens_resposta=%s",
            operacao, modelo,
            getattr(uso, "prompt_tokens", "?"),
            getattr(uso, "completion_tokens", "?"),
        )
    except Exception:  # pragma: no cover - log nunca quebra o fluxo
        pass



# Cliente da OpenAI criado sob demanda.
# Antes era instanciado no import do módulo: com a chave ausente, o SDK
# levanta erro durante o django.setup() e a aplicação inteira não sobe
# (site fora do ar por causa de uma integração opcional).
_client = None


def get_openai_client():
    """Devolve o cliente da OpenAI, criando-o na primeira chamada.

    Levanta RuntimeError com mensagem clara se a chave não estiver
    configurada. As funções que usam a IA tratam essa exceção e devolvem
    uma mensagem de fallback, sem derrubar o restante do sistema.
    """
    global _client
    if _client is None:
        if not getattr(settings, "IA_ATIVA", True):
            raise RuntimeError(
                "Recursos de IA desligados (IA_ATIVA=False)."
            )
        if not settings.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY não configurada: os recursos de IA estão indisponíveis."
            )
        _client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _parametros_ajustados(parametros, mensagem):
    """Corrige parâmetros que a API recusou (modelos novos).

    `max_tokens` → `max_completion_tokens`; remove `temperature` quando o modelo
    não a aceita. Devolve o MESMO dict quando não há o que ajustar (para o
    chamador saber que não vale retentar).
    """
    texto = str(mensagem or "").lower()
    ajustado = dict(parametros)
    mudou = False
    if "max_tokens" in texto and "max_completion_tokens" in texto:
        if "max_tokens" in ajustado:
            ajustado["max_completion_tokens"] = ajustado.pop("max_tokens")
            mudou = True
    if "temperature" in texto and "temperature" in ajustado:
        ajustado.pop("temperature", None)
        mudou = True
    return ajustado if mudou else parametros


async def gerar_chat(chave, *, messages, response_format=None, max_tokens=None,
                     temperature=None):
    """Chama o chat da OpenAI para um contexto, com retry e log centralizados.

    Monta os parâmetros pela configuração do contexto (admin) e, se o modelo
    recusar `max_tokens`/`temperature` (família gpt-5*/o-series), reenvia
    ajustado uma vez. Registra o uso da IA. Levanta em caso de erro real.
    """
    client = get_openai_client()
    kwargs = await ia_config.chamada_kwargs_async(
        chave, max_tokens=max_tokens, temperature=temperature
    )
    parametros = {"messages": messages, **kwargs}
    if response_format:
        parametros["response_format"] = response_format

    try:
        resposta = await client.chat.completions.create(**parametros)
    except openai.BadRequestError as erro:
        ajustado = _parametros_ajustados(parametros, getattr(erro, "message", erro))
        if ajustado is parametros:
            raise
        resposta = await client.chat.completions.create(**ajustado)
        parametros = ajustado

    registrar_uso_ia(chave, parametros["model"], resposta)
    return resposta


async def gerar_mensagem_para_usuario(tipo_usuario):
    """
    Gera uma mensagem personalizada para o usuário com base no seu tipo.
    """

    prompt = f"""Crie uma mensagem motivacional e informativa para um usuário do sistema de eventos. 
                O usuário é um {tipo_usuario}. A mensagem deve ser curta e inspiradora.
                Gere apenas uma frase.
                """
    try:
        response = await gerar_chat(
            "mensagem_usuario",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=70,
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
        response = await gerar_chat(
            "descricao_evento",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=120,
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


# -- Sugestão de categoria (tema) de um evento --
# -- Adicionado por Luciano Vilas Boas --

# Quantas sugestões devolver no máximo (o usuário pediu "duas ou três").
CATEGORIA_MAX_SUGESTOES = 3

# Palavras-chave da rede de segurança, usadas quando a IA não responde.
# Só reconhecem categorias da lista-semente e só quando há evidência no texto:
# a heurística NUNCA inventa um tema novo.
CATEGORIA_PALAVRAS = {
    "formacao": [
        "curso", "formacao", "capacitacao", "oficina", "treinamento", "workshop",
        "palestra", "aula", "minicurso", "ensino", "aprendizagem", "extensao",
    ],
    "ciencia": [
        "ciencia", "cientific", "pesquisa", "snct", "laboratorio", "experimento",
        "academi", "iniciacao cientifica", "divulgacao cientifica",
    ],
    "tecnologia": [
        "tecnologia", "programacao", "software", "hardware", "dados",
        "inteligencia artificial", "llm", "mcp", "python", "html", "css",
        "javascript", "robotica", "computacao", "rede", "codigo", "sistema", "api",
    ],
    "cultura": [
        "cultura", "musica", "teatro", "arte", "danca", "exposicao", "cinema",
        "festival", "literatura", "poesia", "sarau", "patrimonio",
    ],
    "outros": [],
}


def limpar_nome_categoria(bruto):
    """Sanitiza um nome de categoria vindo da IA ou digitado.

    Devolve string vazia quando o nome não serve (vazio, longo demais ou com
    caracteres que não fazem sentido num rótulo de tema).
    """
    nome = " ".join(str(bruto or "").split()).strip(' .,;:-–—"\'')
    if not nome or len(nome) > 60:
        return ""
    if not re.match(r"^[\w\s\-/().&ªºÀ-ÿ]+$", nome):
        return ""
    return nome


def sugerir_categoria_por_palavras(titulo, descricao, valores_validos):
    """Rede de segurança sem IA: escolhe pela contagem de palavras-chave.

    Devolve um valor presente em `valores_validos` ou None sem evidência.
    """
    texto = sem_acento(f"{titulo} {descricao}")
    melhor, melhor_peso = None, 0
    for categoria, palavras in CATEGORIA_PALAVRAS.items():
        if categoria not in valores_validos:
            continue
        peso = sum(1 for p in palavras if p.strip() and p.strip() in texto)
        if peso > melhor_peso:
            melhor, melhor_peso = categoria, peso
    return melhor


async def sugerir_categorias_evento(titulo, descricao, conhecidas, maximo=CATEGORIA_MAX_SUGESTOES):
    """Sugere categorias para o evento a partir do título e da descrição.

    `conhecidas` é a lista de pares (valor, rótulo) das categorias que já
    existem — o mesmo vocabulário que o organizador vê no formulário. A IA é
    instruída a preferir uma delas e, quando nenhuma serve, a propor nomes
    NOVOS de tema.

    Devolve:
        {"sugestoes": [{"categoria", "justificativa", "nova"}, ...],
         "origem": "ia" | "palavras-chave" | None,
         "aviso": str}

    Nada vindo do modelo é aceito sem validação: rótulos existentes são
    casados sem acento/caixa com a lista conhecida; nomes novos passam por
    saneamento (tamanho e caracteres) antes de virar opção para o usuário.
    Quem grava é sempre o formulário, com o texto que o usuário confirmar.
    """
    titulo = (titulo or "").strip()
    descricao = (descricao or "").strip()
    maximo = max(1, min(int(maximo or CATEGORIA_MAX_SUGESTOES), CATEGORIA_MAX_SUGESTOES))

    # mapa sem-acento -> rótulo canônico (aceita tanto o valor quanto o rótulo)
    por_chave = {}
    for valor, rotulo in conhecidas:
        por_chave[sem_acento(rotulo)] = rotulo
        por_chave.setdefault(sem_acento(valor), rotulo)
    rotulos_conhecidos = [rotulo for _, rotulo in conhecidas]
    aviso = ""

    prompt = f"""Você ajuda a classificar eventos de um campus do IFMG.

Categorias que JÁ EXISTEM: {", ".join(rotulos_conhecidos) or "(nenhuma)"}

Título do evento: {titulo}
Descrição: {descricao or "(sem descrição informada)"}

Regras:
1. Se o evento se encaixa em uma das categorias existentes, use exatamente o nome dela.
2. Se nenhuma serve bem, proponha nomes NOVOS de categoria (curtos, 1 a 3 palavras, em português, sem numeração).
3. Dê no máximo {maximo} sugestões, da mais adequada para a menos adequada.
4. Em "nova", diga true somente quando a categoria não existir na lista acima.

Responda SOMENTE com um JSON neste formato:
{{"sugestoes": [{{"categoria": "<nome>", "justificativa": "<frase curta>", "nova": false}}]}}
"""

    try:
        resposta = await gerar_chat(
            "sugerir_categoria",
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=400,
            temperature=0,
        )
        dados = json.loads(resposta.choices[0].message.content or "{}")
        itens = dados.get("sugestoes") or []

        sugestoes, vistas = [], set()
        for item in itens:
            if not isinstance(item, dict):
                continue
            nome = limpar_nome_categoria(item.get("categoria"))
            if not nome:
                continue
            chave = sem_acento(nome)
            if chave in vistas:
                continue
            vistas.add(chave)
            justificativa = " ".join(str(item.get("justificativa", "")).split())[:220]
            canonico = por_chave.get(chave)
            if canonico:
                sugestoes.append({"categoria": canonico, "justificativa": justificativa, "nova": False})
            else:
                sugestoes.append({"categoria": nome, "justificativa": justificativa, "nova": True})
            if len(sugestoes) >= maximo:
                break

        if sugestoes:
            return {"sugestoes": sugestoes, "origem": "ia", "aviso": ""}

        aviso = "A IA não devolveu sugestões utilizáveis; usei a análise por palavras-chave."
    except Exception as e:
        aviso = f"A IA não está disponível agora ({e}); usei a análise por palavras-chave."

    # Rede de segurança: só categoria já conhecida (nunca inventa tema novo).
    valores_seed = [valor for valor, _ in conhecidas if valor in CATEGORIA_PALAVRAS]
    por_palavras = sugerir_categoria_por_palavras(titulo, descricao, valores_seed)
    if por_palavras:
        rotulo = dict(conhecidas).get(por_palavras, por_palavras)
        return {
            "sugestoes": [{
                "categoria": rotulo,
                "justificativa": "Tema reconhecido pelas palavras do título e da descrição.",
                "nova": False,
            }],
            "origem": "palavras-chave",
            "aviso": aviso,
        }

    return {
        "sugestoes": [],
        "origem": None,
        "aviso": aviso or "Não consegui identificar o tema. Escreva uma categoria ou escolha uma existente.",
    }


@csrf_exempt
@login_required
async def sugerir_categoria_ajax(request):
    """Recebe título e descrição e devolve sugestões de categoria."""
    if request.method != "POST":
        return JsonResponse({"erro": "Método não permitido"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"erro": "Corpo da requisição inválido."}, status=400)

    titulo = (data.get("titulo") or "").strip()
    descricao = (data.get("descricao") or "").strip()
    if not titulo:
        return JsonResponse(
            {"erro": "Informe o título do evento antes de pedir a sugestão."}, status=400
        )

    # Import local: mantém este módulo independente dos models no carregamento.
    from .models import categorias_conhecidas

    # A view é assíncrona: consulta ao banco precisa ir para uma thread, senão
    # o Django levanta SynchronousOnlyOperation.
    conhecidas = await sync_to_async(categorias_conhecidas)()
    resultado = await sugerir_categorias_evento(titulo, descricao, conhecidas)
    return JsonResponse(resultado)


# -- Função para notificar eventos via SocketIO --
# --------------------------------------------------------------------------
# Aviso aos clientes conectados (Socket.IO)
# --------------------------------------------------------------------------
# UM cliente persistente por processo. Antes, cada aviso abria conexão nova
# (`AsyncClient` + connect + call + disconnect): medido, ~44 ms de handshake e
# ~42 ms de ida e volta do ack POR NOTIFICAÇÃO — e, com o servidor de socket
# fora do ar, esse `connect` rodava DENTRO da requisição do usuário antes de cair
# no plano B em thread. A conexão agora é reaproveitada e o aviso é um `emit`
# (o protocolo do Socket.IO já garante a entrega enquanto a conexão vive, que
# era o motivo do `call` com confirmação). Sai em milissegundos.
_cliente_socket = None
_trava_socket = threading.Lock()


def _cliente_de_socket():
    """Cliente Socket.IO deste processo, conectado sob demanda."""
    global _cliente_socket
    if _cliente_socket is None:
        _cliente_socket = socketio.Client(reconnection=True)
    if not _cliente_socket.connected:
        _cliente_socket.connect(settings.SOCKET_INTERNAL_URL, wait_timeout=2)
    return _cliente_socket


def notify_socketio(event_type, data):
    """Avisa as telas abertas que algo mudou. Devolve True quando o aviso saiu.

    Nunca levanta exceção e nunca segura o fluxo principal: avisar é acessório,
    o dado já está gravado e as telas têm o polling de segurança. Falhando, o
    cliente é descartado e o próximo aviso tenta conectar de novo.
    """
    global _cliente_socket
    try:
        with _trava_socket:
            _cliente_de_socket().emit(event_type, data)
        return True
    except Exception as erro:
        _cliente_socket = None
        print(f"[SocketIO] Não consegui notificar ({event_type}): {erro}")
        return False




# ---------------------------------------------------------------------------
# Sugestão de tipo de atividade (chamada de propostas)
# ---------------------------------------------------------------------------

# Duas sugestões bastam: o proponente escolhe uma ou escreve a dele.
TIPO_MAX_SUGESTOES = 2

# Rede de segurança sem IA: tipos comuns do campus e as palavras que os
# denunciam. Só vale quando não há tipo existente casando com o texto.
TIPO_PALAVRAS = {
    "Palestra": ["palestra", "conversa", "bate-papo", "mesa-redonda", "painel",
                 "debate", "roda de conversa"],
    "Minicurso": ["minicurso", "curso", "aula", "capacitacao", "treinamento",
                  "tutorial", "introducao a"],
    "Oficina": ["oficina", "workshop", "pratica", "mao na massa", "maker",
                "laboratorio"],
    "Apresentação cultural": ["cultural", "musica", "teatro", "danca", "arte",
                              "sarau", "poesia", "show", "apresentacao"],
    "Exposição": ["exposicao", "mostra", "feira", "stand"],
    "Competição": ["competicao", "torneio", "maratona", "hackathon", "olimpiada",
                   "campeonato", "gincana"],
    "Visita técnica": ["visita", "tour", "passeio"],
    "Reunião": ["reuniao", "encontro", "assembleia", "planejamento"],
}


def sugerir_tipo_por_palavras(titulo, descricao, nomes_conhecidos):
    """Rede de segurança sem IA. Devolve `(nome, existente)`.

    Primeiro tenta achar um tipo JÁ EXISTENTE cujo nome apareça no texto; só
    depois recorre às palavras-chave, e aí o nome é novo (para o proponente
    gravar como sugestão).
    """
    texto = sem_acento(f"{titulo} {descricao}")
    for nome in nomes_conhecidos:
        chave = sem_acento(nome)
        if chave and chave in texto:
            return nome, True

    melhor, peso = None, 0
    for nome, palavras in TIPO_PALAVRAS.items():
        peso_atual = sum(1 for palavra in palavras if palavra in texto)
        if peso_atual > peso:
            melhor, peso = nome, peso_atual
    if not melhor:
        return "", False

    por_nome = {sem_acento(nome): nome for nome in nomes_conhecidos}
    existente = por_nome.get(sem_acento(melhor))
    return (existente, True) if existente else (melhor, False)


async def sugerir_tipos_atividade(titulo, descricao, conhecidos,
                                  maximo=TIPO_MAX_SUGESTOES):
    """Sugere tipos de atividade, preferindo os que já existem no catálogo.

    `conhecidos` é a lista de dicts `{"id", "nome"}`. Nada vindo do modelo é
    aceito sem validação: nomes casados com o catálogo viram sugestão de tipo
    existente (com o id, para o formulário selecionar) e nomes novos passam por
    saneamento — o proponente grava em `tipo_sugerido` e o organizador
    normaliza na aprovação.

    Devolve:
        {"sugestoes": [{"nome", "existente", "id", "justificativa"}],
         "origem": "ia" | "palavras-chave" | None,
         "aviso": str}
    """
    titulo = (titulo or "").strip()
    descricao = (descricao or "").strip()
    maximo = max(1, min(int(maximo or TIPO_MAX_SUGESTOES), TIPO_MAX_SUGESTOES))

    por_chave = {sem_acento(item["nome"]): item for item in conhecidos}
    nomes = [item["nome"] for item in conhecidos]
    aviso = ""

    prompt = f"""Você ajuda a classificar atividades de um evento de um campus do IFMG.

Tipos de atividade que JÁ EXISTEM: {", ".join(nomes) or "(nenhum)"}

Título da atividade: {titulo}
Descrição: {descricao or "(sem descrição informada)"}

Regras:
1. Se a atividade se encaixa em um tipo existente, use exatamente o nome dele.
2. Se nenhum serve bem, proponha nomes NOVOS (curtos, 1 a 3 palavras, em português, sem numeração).
3. Dê no máximo {maximo} sugestões, da mais adequada para a menos adequada.
4. Em "novo", diga true somente quando o tipo não existir na lista acima.

Responda SOMENTE com um JSON neste formato:
{{"sugestoes": [{{"nome": "<nome>", "justificativa": "<frase curta>", "novo": false}}]}}
"""

    try:
        resposta = await gerar_chat(
            "sugerir_tipo",
            messages=[{"role": "system", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=300,
            temperature=0,
        )
        dados = json.loads(resposta.choices[0].message.content or "{}")

        sugestoes, vistas = [], set()
        for item in dados.get("sugestoes") or []:
            if not isinstance(item, dict):
                continue
            nome = limpar_nome_categoria(item.get("nome"))[:40].strip()
            if not nome:
                continue
            chave = sem_acento(nome)
            if chave in vistas:
                continue
            vistas.add(chave)
            justificativa = " ".join(str(item.get("justificativa", "")).split())[:220]
            existente = por_chave.get(chave)
            if existente:
                sugestoes.append({
                    "nome": existente["nome"], "existente": True,
                    "id": existente["id"], "justificativa": justificativa,
                })
            else:
                sugestoes.append({
                    "nome": nome, "existente": False, "id": None,
                    "justificativa": justificativa,
                })
            if len(sugestoes) >= maximo:
                break

        if sugestoes:
            return {"sugestoes": sugestoes, "origem": "ia", "aviso": ""}

        aviso = "A IA não devolveu sugestões utilizáveis; usei a análise por palavras-chave."
    except Exception as e:
        aviso = f"A IA não está disponível agora ({e}); usei a análise por palavras-chave."

    nome, existente = sugerir_tipo_por_palavras(titulo, descricao, nomes)
    if nome:
        item = por_chave.get(sem_acento(nome))
        return {
            "sugestoes": [{
                "nome": nome,
                "existente": existente,
                "id": item["id"] if item else None,
                "justificativa": "Reconhecido pelas palavras do título e da descrição.",
            }],
            "origem": "palavras-chave",
            "aviso": aviso,
        }

    return {
        "sugestoes": [],
        "origem": None,
        "aviso": aviso or (
            "Não consegui identificar o tipo. Escolha um da lista ou escreva um nome novo."
        ),
    }


@csrf_exempt
@login_required
async def sugerir_tipo_ajax(request):
    """Recebe título e descrição e devolve sugestões de tipo de atividade."""
    if request.method != "POST":
        return JsonResponse({"erro": "Método não permitido"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"erro": "Corpo da requisição inválido."}, status=400)

    titulo = (data.get("titulo") or "").strip()
    descricao = (data.get("descricao") or "").strip()
    if not titulo:
        return JsonResponse(
            {"erro": "Informe o título da atividade antes de pedir a sugestão."},
            status=400,
        )

    from .models import TipoAtividade

    # A view é assíncrona: consulta ao banco precisa ir para uma thread.
    conhecidos = await sync_to_async(list)(
        TipoAtividade.objects.order_by("nome").values("id", "nome")
    )
    resultado = await sugerir_tipos_atividade(titulo, descricao, conhecidos)
    return JsonResponse(resultado)
