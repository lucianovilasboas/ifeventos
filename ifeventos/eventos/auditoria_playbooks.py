"""Playbooks de erro do AuditorIA: assinatura conhecida → causa e solução.

O diagnóstico (`eventos/auditor_diagnostico.py`) agrupa os erros e casa cada
grupo contra esta lista. Onde há playbook, a **causa provável** e a **solução**
saem daqui — concretas e revisáveis — em vez de inventadas pela IA. Onde não há,
a IA propõe a causa mais provável usando o `MAPA_LOGGERS` e o traceback.

Não é regra de negócio: é conhecimento operacional. Editar por PR é o caminho
(curto, versionado, sem migração). Cada item:

    id            identificador estável
    correspondencias  trechos (case-insensitive) que casam no resumo/traceback
    loggers       (opcional) prefixos de logger que também casam
    titulo        frase curta do problema
    severidade    "critico" | "alto" | "medio" | "baixo"
    causa         causa provável
    solucao       o que fazer
    onde          arquivo/módulo onde olhar
"""

PLAYBOOKS = [
    {
        "id": "engineio-websocket-client",
        "correspondencias": ["websocket-client package not installed"],
        "loggers": ["engineio", "socketio"],
        "titulo": "Socket.IO do servidor sem transporte websocket",
        "severidade": "baixo",
        "causa": (
            "O pacote websocket-client não está instalado no contêiner; o cliente "
            "Socket.IO cai em HTTP long-polling e loga um ERROR a cada conexão."
        ),
        "solucao": (
            "Manter websocket-client no requirements e rebuildar a imagem; os "
            "loggers engineio/socketio ficam só no console (fora da auditoria)."
        ),
        "onde": "requirements.txt · setup/settings.py (LOGGING)",
    },
    {
        "id": "async-orm",
        "correspondencias": [
            "SynchronousOnlyOperation",
            "You cannot call this from an async context",
        ],
        "titulo": "ORM do Django chamado de contexto async",
        "severidade": "alto",
        "causa": (
            "Uma view/função async acessou o ORM sem sync_to_async — o Django "
            "bloqueia consultas síncronas dentro de um event loop."
        ),
        "solucao": (
            "Envolver a consulta em sync_to_async (ou tornar a view síncrona, "
            "como em `organizador/views.py:auditoria_responder`)."
        ),
        "onde": "views async (ex.: eventos/views.py, participante/views.py)",
    },
    {
        "id": "inscricao-duplicada",
        "correspondencias": [
            "unique_inscricao",
            "duplicate key value violates unique constraint",
            "unique_presenca",
        ],
        "titulo": "Violação de unicidade (inscrição/presença duplicada)",
        "severidade": "medio",
        "causa": (
            "Duas gravações concorrentes para a mesma pessoa/atividade — a "
            "constraint unique_inscricao/unique_presenca barrou a segunda."
        ),
        "solucao": (
            "Usar get_or_create no caminho que grava; se vier de um clique duplo, "
            "é comportamento esperado do banco."
        ),
        "onde": "eventos/inscricoes.py · eventos/crachas.py (registrar_presenca)",
    },
    {
        "id": "email",
        "correspondencias": [
            "SMTP",
            "smtplib",
            "Authentication failed",
            "Connection refused",
            "getaddrinfo",
        ],
        "loggers": ["eventos.emails", "django.core.mail"],
        "titulo": "Falha ao enviar e-mail",
        "severidade": "medio",
        "causa": (
            "SMTP inacessível/credencial inválida. O envio é assíncrono e não "
            "segura a requisição, mas o e-mail não sai."
        ),
        "solucao": (
            "Conferir EMAIL_* no .env (host, porta, TLS, usuário/senha) e a "
            "conectividade de saída do servidor."
        ),
        "onde": "eventos/emails.py · eventos/mail_backend.py · .env",
    },
    {
        "id": "openai",
        "correspondencias": [
            "openai",
            "RateLimitError",
            "insufficient_quota",
            "Invalid API key",
            "APIConnectionError",
        ],
        "loggers": ["eventos.ia", "eventos.services", "openai"],
        "titulo": "Falha na chamada à IA (OpenAI)",
        "severidade": "medio",
        "causa": (
            "Chave ausente/inválida, cota esgotada ou limite de requisições. As "
            "telas de IA (copiloto, assistente, relatórios) degradam."
        ),
        "solucao": (
            "Verificar OPENAI_API_KEY e cota; os fluxos têm fallback determinístico "
            "quando a IA falha."
        ),
        "onde": "eventos/services.py · eventos/ia_config.py · .env",
    },
    {
        "id": "socket-notify",
        "correspondencias": ["[SocketIO]", "Não consegui notificar"],
        "loggers": ["eventos.services"],
        "titulo": "Aviso em tempo real não entregue",
        "severidade": "baixo",
        "causa": (
            "O cliente Socket.IO do processo não conseguiu conectar/emitir ligado "
            "a SOCKET_INTERNAL_URL."
        ),
        "solucao": (
            "Conferir se o uvicorn (porta 8500) está de pé e SOCKET_INTERNAL_URL. "
            "Avisar é acessório: as telas têm polling de segurança."
        ),
        "onde": "eventos/services.py (notify_socketio) · entrypoint.sh",
    },
]


# Logger → o que ele cobre. Ajuda a IA a apontar "onde olhar" quando não há
# playbook (e a entender o contexto de um erro).
MAPA_LOGGERS = {
    "django.request": "Requisições HTTP (views). 5xx = exceção na view; 4xx = cliente/rota.",
    "django.security": "Segurança (CSRF, hosts, permissões).",
    "eventos.ia": "Camada de IA (chamadas à OpenAI, contextos).",
    "eventos.services": "Serviços: socket em tempo real, IA, e-mails.",
    "eventos.crachas": "Crachás, QR de presença, cartazes (PDF) e check-in.",
    "eventos.certificados": "Emissão e renderização de certificados (PDF/.docx).",
    "eventos.auditor_ia": "Agente de auditoria (perguntas sobre o histórico).",
    "eventos.auditor_diagnostico": "Diagnóstico automático da trilha de auditoria.",
    "organizador": "Painel do organizador (views).",
    "api": "API REST (/api/v1/).",
    "engineio": "Transporte do Socket.IO.",
    "socketio": "Socket.IO.",
    "openai": "SDK da OpenAI.",
}


def _normalizar(texto):
    return (texto or "").lower()


def playbooks_para(texto, logger=None):
    """Playbooks que casam com o texto do erro (e/ou com o logger).

    Casa por trecho no texto (resumo + traceback) OU pelo prefixo do logger.
    Devolve a lista de playbooks correspondentes (pode ser vazia).
    """
    alvo = _normalizar(texto)
    encontrados = []
    for pb in PLAYBOOKS:
        casa_texto = any(_normalizar(trecho) in alvo for trecho in pb["correspondencias"])
        casa_logger = bool(logger) and any(
            _normalizar(logger).startswith(_normalizar(prefixo))
            for prefixo in pb.get("loggers", [])
        )
        if (casa_texto or casa_logger) and pb not in encontrados:
            encontrados.append(pb)
    return encontrados


def topico_do_logger(logger):
    """Explicação curta do que um logger cobre (ou "" se desconhecido)."""
    nome = logger or ""
    if nome in MAPA_LOGGERS:
        return MAPA_LOGGERS[nome]
    for chave, valor in MAPA_LOGGERS.items():
        if nome.startswith(chave + "."):
            return valor
    return ""
