"""Comunicação por e-mail do organizador com as pessoas do evento.

Reúne quem tem vínculo com o evento (organizadores, palestrantes, equipe de
apoio, comissão e inscritos), resolve a seleção de grupos + pessoas, deduplica
e envia **um e-mail por pessoa** — sem CC/BCC, para ninguém ver o endereço dos
outros. O envio usa o backend configurado (assíncrono em produção) e é
best-effort, como o resto do sistema.

As regras de quem pode gerenciar o evento continuam em `crachas.py`
(`pode_gerenciar_evento`); aqui fica só o domínio dos destinatários e do envio.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core import mail
from django.core.mail import EmailMessage

from .models import Inscricao, Participante

logger = logging.getLogger(__name__)

# Papéis que uma pessoa pode ter no evento. A mesma pessoa pode acumular mais
# de um (ex.: organiza e também palestra) e entra uma vez só no envio.
PAPEIS = {
    "organizador": "Organizador",
    "coorganizador": "Co-organizador",
    "palestrante": "Palestrante",
    "equipe": "Equipe de apoio",
    "comissao": "Comissão organizadora",
    "participante": "Participante",
}

# Grupos por papel, na ordem da tela: (chave, rótulo, papéis incluídos).
GRUPOS = (
    ("organizadores", "Organizadores", ("organizador", "coorganizador")),
    ("palestrantes", "Palestrantes", ("palestrante",)),
    ("equipe", "Equipe de apoio", ("equipe",)),
    ("comissao", "Comissão organizadora", ("comissao",)),
    ("participantes", "Participantes", ("participante",)),
)

GRUPO_ATIVIDADE = "inscritos_atividade"
GRUPO_TODOS = "todos"
ROTULO_TODOS = "Todos os relacionados"

_PAPEIS_DO_GRUPO = {chave: papeis for chave, _rotulo, papeis in GRUPOS}


# ---------------------------------------------------------------------------
# Pessoas e grupos
# ---------------------------------------------------------------------------
def pessoas_do_evento(evento):
    """Pessoas relacionadas ao evento, com TODOS os papéis, por nome.

    Inclui o organizador dono, co-organizadores, equipe de apoio, comissão,
    palestrantes de qualquer atividade e inscritos. Devolve uma lista de
    `{"pessoa": Participante, "papeis": [chaves]}` em ordem alfabética.
    """
    papeis = {}

    def marcar(pessoa, papel):
        if pessoa is None or not getattr(pessoa, "pk", None):
            return
        papeis.setdefault(pessoa.pk, set()).add(papel)

    if evento.organizador_id:
        marcar(evento.organizador, "organizador")
    for pessoa in evento.organizadores.all():
        marcar(pessoa, "coorganizador")
    for pessoa in evento.equipe.all():
        marcar(pessoa, "equipe")
    for pessoa in evento.comissao.all():
        marcar(pessoa, "comissao")
    for pessoa in Participante.objects.filter(atividades__evento=evento).distinct():
        marcar(pessoa, "palestrante")
    for pessoa in Participante.objects.filter(
        inscricoes__atividade__evento=evento
    ).distinct():
        marcar(pessoa, "participante")

    pessoas = Participante.objects.filter(pk__in=papeis.keys())
    linhas = [
        {
            "pessoa": pessoa,
            "papeis": [papel for papel in PAPEIS if papel in papeis[pessoa.pk]],
        }
        for pessoa in pessoas
    ]
    linhas.sort(key=lambda linha: (
        (linha["pessoa"].first_name or "").casefold(),
        (linha["pessoa"].last_name or "").casefold(),
        linha["pessoa"].pk,
    ))
    return linhas


def _ids_do_grupo(linhas, chave):
    """Ids das pessoas que pertencem ao grupo (vazio para chave desconhecida)."""
    if chave == GRUPO_TODOS:
        return {linha["pessoa"].pk for linha in linhas}
    papeis = set(_PAPEIS_DO_GRUPO.get(chave, ()))
    if not papeis:
        return set()
    return {
        linha["pessoa"].pk
        for linha in linhas
        if papeis & set(linha["papeis"])
    }


def grupos_com_contagem(evento):
    """Grupos por papel com a contagem de pessoas (para os cartões da tela)."""
    linhas = pessoas_do_evento(evento)
    grupos = [
        {"chave": chave, "rotulo": rotulo, "total": len(_ids_do_grupo(linhas, chave))}
        for chave, rotulo, _papeis in GRUPOS
    ]
    grupos.append({
        "chave": GRUPO_TODOS,
        "rotulo": ROTULO_TODOS,
        "total": len(linhas),
    })
    return grupos


def atividade_do_evento(evento, atividade_id):
    """Atividade do evento pelo id (None se não pertencer a este evento)."""
    try:
        atividade_id = int(atividade_id or 0)
    except (TypeError, ValueError):
        return None
    if not atividade_id:
        return None
    return evento.atividades.filter(pk=atividade_id).first()


def _ids_inscritos_atividade(atividade):
    if atividade is None:
        return set()
    return set(
        Inscricao.objects.filter(atividade=atividade).values_list(
            "participante_id", flat=True
        )
    )


def _resolver_selecao(evento, grupos=None, pessoas_ids=None, atividade_id=None,
                      excluir=None):
    """Resolve grupos + individuais em ids, separando o que foi descartado.

    A exclusão (`excluir`, o organizador logado) vale só para os GRUPOS; os
    individuais entram depois, então uma escolha explícita nunca é anulada.
    Devolve também os contadores que a tela usa para explicar o total.
    """
    linhas = pessoas_do_evento(evento)
    por_id = {linha["pessoa"].pk: linha["pessoa"] for linha in linhas}

    grupos_ids = set()
    atividade = atividade_do_evento(evento, atividade_id)
    for chave in set(grupos or []):
        if chave == GRUPO_ATIVIDADE:
            grupos_ids.update(_ids_inscritos_atividade(atividade))
        else:
            grupos_ids.update(_ids_do_grupo(linhas, chave))

    individuais = []
    nao_relacionados = set()
    for valor in pessoas_ids or []:
        try:
            pessoa_id = int(valor)
        except (TypeError, ValueError):
            continue
        if pessoa_id in por_id:
            if pessoa_id not in individuais:
                individuais.append(pessoa_id)
        else:
            nao_relacionados.add(pessoa_id)

    selecionados = set(grupos_ids)
    removido = False
    alvo = getattr(excluir, "pk", excluir) if excluir is not None else None
    if alvo is not None and alvo in selecionados:
        removido = True
        selecionados.discard(alvo)
    selecionados.update(individuais)

    return {
        "por_id": por_id,
        "selecionados": selecionados,
        "grupos_ids": grupos_ids,
        "individuais": individuais,
        "repetidos": len(set(individuais) & grupos_ids),
        "nao_relacionados": len(nao_relacionados),
        # "fora" só conta se a pessoa não voltou pela seleção individual.
        "excluido": 1 if removido and alvo not in selecionados else 0,
    }


def _pessoas_por_email(por_id, selecionados):
    """Pessoas correspondentes aos ids, deduplicadas por e-mail."""
    vistos = set()
    pessoas = []
    sem_email = []
    for pessoa_id in sorted(selecionados):
        pessoa = por_id.get(pessoa_id)
        if pessoa is None:
            continue
        email = (pessoa.email or "").strip().lower()
        if not email:
            sem_email.append(pessoa)
            continue
        if email in vistos:
            continue
        vistos.add(email)
        pessoas.append(pessoa)
    return pessoas, sem_email


def destinatarios(evento, grupos=None, pessoas_ids=None, atividade_id=None,
                  excluir=None):
    """Resolve grupos + seleção individual em pessoas deduplicadas.

    Devolve `(pessoas, sem_email)`. A deduplicação final é por e-mail
    (minúsculo): quem está em dois grupos recebe uma mensagem só. Pessoas sem
    e-mail válido saem em `sem_email` para a tela avisar. Ids de pessoas que
    não têm vínculo com o evento são ignorados.

    `excluir` (o organizador logado, quando “não me incluir” está marcado) vale
    apenas para os GRUPOS. Uma pessoa escolhida individualmente continua na
    lista: a escolha explícita vence a exclusão automática.
    """
    dados = _resolver_selecao(
        evento, grupos=grupos, pessoas_ids=pessoas_ids,
        atividade_id=atividade_id, excluir=excluir,
    )
    return _pessoas_por_email(dados["por_id"], dados["selecionados"])


def resumo_selecao(evento, grupos=None, pessoas_ids=None, atividade_id=None,
                   excluir=None):
    """Contagens para a tela explicar o total (únicos x sobreposição).

    Devolve `total` (quem recebe), `grupos` (pessoas únicas nos grupos),
    `repetidos` (individuais já incluídos nos grupos), `excluido` (1 quando o
    organizador saiu pelo “não me incluir”), `nao_relacionados` (ids sem
    vínculo com o evento) e `ignorados` (sem e-mail).
    """
    dados = _resolver_selecao(
        evento, grupos=grupos, pessoas_ids=pessoas_ids,
        atividade_id=atividade_id, excluir=excluir,
    )
    pessoas, sem_email = _pessoas_por_email(
        dados["por_id"], dados["selecionados"]
    )
    return {
        "total": len(pessoas),
        "grupos": len(dados["grupos_ids"]),
        "repetidos": dados["repetidos"],
        "excluido": dados["excluido"],
        "nao_relacionados": dados["nao_relacionados"],
        "ignorados": len(sem_email),
    }


def buscar_pessoas(evento, termo="", limite=20):
    """Busca individual por nome ou e-mail, restrita ao evento."""
    termo = (termo or "").strip().casefold()
    linhas = pessoas_do_evento(evento)
    if termo:
        def combina(linha):
            pessoa = linha["pessoa"]
            nome = (pessoa.get_full_name() or "").casefold()
            email = (pessoa.email or "").casefold()
            return termo in nome or termo in email

        linhas = [linha for linha in linhas if combina(linha)]

    return [
        {
            "id": linha["pessoa"].pk,
            "nome": linha["pessoa"].get_full_name() or linha["pessoa"].email,
            "email": linha["pessoa"].email,
            "papeis": [PAPEIS[papel] for papel in linha["papeis"]],
            "tem_email": bool((linha["pessoa"].email or "").strip()),
        }
        for linha in linhas[:limite]
    ]


def pessoas_por_ids(evento, ids):
    """Pessoas do evento correspondentes aos ids, na ordem recebida.

    Usado para redesenhar a tela depois de um erro de validação, sem confiar
    que o id ainda pertence ao evento.
    """
    try:
        ids = [int(valor) for valor in (ids or [])]
    except (TypeError, ValueError):
        ids = []
    if not ids:
        return []
    permitidos = {
        linha["pessoa"].pk: linha["pessoa"] for linha in pessoas_do_evento(evento)
    }
    return [permitidos[pk] for pk in ids if pk in permitidos]


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------
def max_destinatarios():
    """Limite por disparo (0 = sem limite). Configurável em settings/.env."""
    try:
        return int(getattr(settings, "COMUNICADOS_MAX_DESTINATARIOS", 300) or 0)
    except (TypeError, ValueError):
        return 300


def enviar_comunicado(assunto, corpo, pessoas, reply_to=None):
    """Envia o mesmo texto para cada pessoa, em mensagens INDIVIDUAIS.

    Devolve quantas mensagens foram entregues ao backend (em produção, o
    backend assíncrono as enfileira). Nunca levanta: falha de SMTP vai para o
    log e o retorno 0 sinaliza que nada saiu.
    """
    remetente = getattr(settings, "DEFAULT_FROM_EMAIL", None)
    mensagens = []
    for pessoa in pessoas:
        email = (pessoa.email or "").strip()
        if not email:
            continue
        mensagem = EmailMessage(assunto, corpo, remetente, [email])
        if reply_to:
            mensagem.reply_to = [reply_to]
        mensagens.append(mensagem)

    if not mensagens:
        return 0
    try:
        connection = mail.get_connection()
        connection.send_messages(mensagens)
    except Exception:  # noqa: BLE001 - e-mail é acessório, não derruba a ação
        logger.exception(
            "Falha ao enviar comunicado para %s destinatário(s)", len(mensagens)
        )
        return 0
    return len(mensagens)


def envios_recentes(evento, limite=5):
    """Últimos comunicados do evento registrados na auditoria."""
    from .models import RegistroAuditoria

    return list(
        RegistroAuditoria.objects.filter(
            evento=evento, acao=RegistroAuditoria.ACAO_ENVIAR_COMUNICADO
        ).order_by("-criado_em", "-id")[:limite]
    )
