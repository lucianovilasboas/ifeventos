"""Comunicação por e-mail do organizador com as pessoas do evento.

Reúne quem tem vínculo com o evento (organizadores, palestrantes, equipe de
apoio, comissão e inscritos), resolve a seleção de grupos + pessoas e
deduplica por e-mail. O envio não acontece na requisição: vira um
`ComunicadoJob` (fila em banco), processado pelo worker
`manage.py processar_comunicados`, que envia **um e-mail por pessoa** (sem
CC/BCC), em lotes, com progresso e reenvio apenas das falhas.

As regras de quem pode gerenciar o evento continuam em `crachas.py`
(`pode_gerenciar_evento`); aqui fica só o domínio dos destinatários e da fila.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import auditoria
from .models import (
    ComunicadoDestinatario,
    ComunicadoJob,
    Inscricao,
    Notificacao,
    Participante,
    RegistroAuditoria,
)

logger = logging.getLogger(__name__)

# Tamanho do lote e pausa entre lotes (evita rajada no SMTP/Gmail).
TAM_LOTE = 10
INTERVALO_LOTE = 2
# Job preso em "processando" por mais que isto é reciclado para "pendente".
MINUTOS_PRESO = 30

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


def job_em_andamento(evento):
    """Job pendente/processando do evento (ou None).

    A tela usa isso para mostrar o aviso “envio em andamento” e para impedir
    dois disparos simultâneos no mesmo evento.
    """
    return (
        ComunicadoJob.objects.filter(
            evento=evento,
            status__in=[
                ComunicadoJob.STATUS_PENDENTE,
                ComunicadoJob.STATUS_PROCESSANDO,
            ],
        )
        .order_by("-criado_em", "-id")
        .first()
    )


def criar_job(*, evento, assunto, corpo, grupos, pessoas, atividade=None,
              criado_por=None):
    """Cria o job e congela os destinatários. Devolve o `ComunicadoJob`.

    O snapshot (nome/e-mail) protege o envio de mudanças posteriores no perfil
    e permite reenviar só as falhas. Não valida nada de negócio: o chamador já
    resolveu/validou os destinatários.
    """
    with transaction.atomic():
        job = ComunicadoJob.objects.create(
            evento=evento,
            criado_por=criado_por,
            assunto=assunto,
            corpo=corpo,
            grupos=list(grupos or []),
            atividade=atividade,
        )
        vistos = set()
        destinatarios = []
        for pessoa in pessoas:
            email = (pessoa.email or "").strip()
            if not email or email.lower() in vistos:
                continue
            vistos.add(email.lower())
            destinatarios.append(ComunicadoDestinatario(
                job=job,
                participante=pessoa,
                nome=(pessoa.get_full_name() or pessoa.email or "")[:255],
                email=email,
            ))
        ComunicadoDestinatario.objects.bulk_create(destinatarios)
        job.total = len(destinatarios)
        job.save(update_fields=["total"])
    return job


def _conexao_sincrona():
    """Conexão SMTP do worker, mesmo com o backend async no site.

    O backend assíncrono devolve o controle antes do envio e não informa
    falhas — no worker precisamos do resultado por destinatário. Em dev/teste
    (locmem/console) o backend configurado continua valendo.
    """
    backend = getattr(settings, "EMAIL_BACKEND", "")
    if backend == "eventos.mail_backend.AsyncEmailBackend":
        backend = "django.core.mail.backends.smtp.EmailBackend"
    return get_connection(backend=backend)


def _atualizar_progresso(job, *, total, processados, enviados, falhas):
    ComunicadoJob.objects.filter(pk=job.pk).update(
        total=total,
        processados=processados,
        enviados=enviados,
        falhas=falhas,
    )


def _finalizar_job(job, *, enviados, falhas):
    """Fecha o job, audita e notifica o autor."""
    mensagem = "%s enviado(s)" % enviados
    if falhas:
        mensagem += ", %s falha(s)" % falhas
    status = (
        ComunicadoJob.STATUS_CONCLUIDO
        if enviados or not falhas
        else ComunicadoJob.STATUS_FALHOU
    )
    ComunicadoJob.objects.filter(pk=job.pk).update(
        status=status,
        mensagem=mensagem,
        concluido_em=timezone.now(),
    )
    _auditar(job, enviados, falhas)
    _notificar(job, enviados, falhas, status)
    job.refresh_from_db()
    return job


def _auditar(job, enviados, falhas):
    auditoria.registrar(
        acao=RegistroAuditoria.ACAO_ENVIAR_COMUNICADO,
        objeto=job.evento,
        evento=job.evento,
        usuario=job.criado_por,
        resumo="Enviou comunicado: %s (%s e-mail(s))" % (job.assunto, enviados),
        detalhes={
            "assunto": job.assunto,
            "grupos": job.grupos,
            "atividade_id": job.atividade_id,
            "total": job.total,
            "enviados": enviados,
            "falhas": falhas,
        },
    )


def _notificar(job, enviados, falhas, status):
    """Cria a notificação persistente do autor (sino no topo)."""
    if not job.criado_por_id:
        return
    titulo = (
        "Comunicado enviado"
        if status == ComunicadoJob.STATUS_CONCLUIDO
        else "Comunicado com falhas"
    )
    mensagem = "%s de %s e-mail(s) enviados." % (enviados, job.total)
    if falhas:
        mensagem += " %s falha(s)." % falhas
    Notificacao.objects.create(
        usuario=job.criado_por,
        evento=job.evento,
        tipo=Notificacao.TIPO_COMUNICADO,
        titulo=titulo,
        mensagem=mensagem,
        url=reverse("organizador:comunicacao_evento", args=[job.evento_id]),
    )


def processar_job(job):
    """Envia os destinatários PENDENTES do job, em lotes. Devolve o job.

    Idempotente por destinatário: só linhas pendentes são enviadas, então um
    job retomado após queda do worker (ou o reenvio de falhas) nunca duplica
    quem já recebeu.
    """
    ComunicadoJob.objects.filter(pk=job.pk).update(
        status=ComunicadoJob.STATUS_PROCESSANDO,
        iniciado_em=timezone.now(),
    )
    job.refresh_from_db()

    enviados = job.destinatarios.filter(
        status=ComunicadoDestinatario.STATUS_ENVIADO
    ).count()
    falhas = job.destinatarios.filter(
        status=ComunicadoDestinatario.STATUS_FALHOU
    ).count()
    pendentes = list(
        job.destinatarios.filter(
            status=ComunicadoDestinatario.STATUS_PENDENTE
        ).order_by("id")
    )
    total = enviados + falhas + len(pendentes)
    processados = enviados + falhas
    _atualizar_progresso(
        job, total=total, processados=processados,
        enviados=enviados, falhas=falhas,
    )

    remetente = getattr(settings, "DEFAULT_FROM_EMAIL", None)
    reply_to = job.criado_por.email if job.criado_por_id else None
    tamanho = max(
        1, int(getattr(settings, "COMUNICADOS_TAM_LOTE", TAM_LOTE) or TAM_LOTE)
    )
    intervalo = max(
        0, int(getattr(settings, "COMUNICADOS_INTERVALO_LOTE", INTERVALO_LOTE))
    )

    for inicio in range(0, len(pendentes), tamanho):
        lote = pendentes[inicio:inicio + tamanho]
        conexao = _conexao_sincrona()
        try:
            conexao.open()
        except Exception as erro:  # noqa: BLE001 - SMTP é externo
            logger.exception("comunicados: falha ao abrir SMTP no job %s", job.pk)
            erro_txt = ("Falha ao conectar no SMTP: %s" % erro)[:255]
            ids_do_lote = [destino.id for destino in lote]
            ComunicadoDestinatario.objects.filter(id__in=ids_do_lote).update(
                status=ComunicadoDestinatario.STATUS_FALHOU,
                erro=erro_txt,
                enviado_em=None,
            )
            falhas += len(ids_do_lote)
            processados += len(ids_do_lote)
            # O restante da fila falharia pelo mesmo motivo: marca tudo como
            # falho para o reenvio ser preciso (e não insistir no SMTP fora).
            restantes = job.destinatarios.filter(
                status=ComunicadoDestinatario.STATUS_PENDENTE
            )
            quantidade = restantes.count()
            if quantidade:
                restantes.update(
                    status=ComunicadoDestinatario.STATUS_FALHOU,
                    erro=erro_txt,
                    enviado_em=None,
                )
                falhas += quantidade
                processados += quantidade
            _atualizar_progresso(
                job, total=total, processados=processados,
                enviados=enviados, falhas=falhas,
            )
            return _finalizar_job(job, enviados=enviados, falhas=falhas)

        for destino in lote:
            if reply_to:
                mensagem = EmailMessage(
                    job.assunto, job.corpo, remetente, [destino.email],
                    reply_to=[reply_to],
                )
            else:
                mensagem = EmailMessage(
                    job.assunto, job.corpo, remetente, [destino.email]
                )
            try:
                conexao.send_messages([mensagem])
                destino.status = ComunicadoDestinatario.STATUS_ENVIADO
                destino.erro = ""
                destino.enviado_em = timezone.now()
                enviados += 1
            except Exception as erro:  # noqa: BLE001 - erro de um destinatário
                destino.status = ComunicadoDestinatario.STATUS_FALHOU
                destino.erro = str(erro)[:255]
                destino.enviado_em = None
                falhas += 1
            destino.save(update_fields=["status", "erro", "enviado_em"])
            processados += 1

        try:
            conexao.close()
        except Exception:  # noqa: BLE001 - fechar conexão é acessório
            pass
        _atualizar_progresso(
            job, total=total, processados=processados,
            enviados=enviados, falhas=falhas,
        )
        if intervalo and inicio + tamanho < len(pendentes):
            time.sleep(intervalo)

    return _finalizar_job(job, enviados=enviados, falhas=falhas)


def processar_proximo_job():
    """Reivindica e processa o próximo job pendente (claim atômico)."""
    with transaction.atomic():
        job = (
            ComunicadoJob.objects.select_for_update(skip_locked=True)
            .filter(status=ComunicadoJob.STATUS_PENDENTE)
            .order_by("criado_em", "id")
            .first()
        )
        if job is None:
            return None
        ComunicadoJob.objects.filter(pk=job.pk).update(
            status=ComunicadoJob.STATUS_PROCESSANDO,
            iniciado_em=timezone.now(),
        )

    try:
        processar_job(job)
    except Exception:  # noqa: BLE001 - task em background
        logger.exception("comunicados: job %s falhou", job.pk)
        ComunicadoJob.objects.filter(pk=job.pk).update(
            status=ComunicadoJob.STATUS_FALHOU,
            mensagem="Erro ao processar o envio.",
            concluido_em=timezone.now(),
        )
    return job


def reciclar_presos():
    """Devolve jobs presos em `processando` (worker caiu) para `pendente`."""
    limite = timezone.now() - timedelta(minutes=MINUTOS_PRESO)
    return ComunicadoJob.objects.filter(
        status=ComunicadoJob.STATUS_PROCESSANDO,
        iniciado_em__lt=limite,
    ).update(status=ComunicadoJob.STATUS_PENDENTE, iniciado_em=None)


def reenviar_falhas(job):
    """Devolve as linhas FALHOU para a fila. Devolve quantas foram reenfileiradas.

    Quem já recebeu fica como `enviado` e não é tocado; o progresso recomeça
    em `enviados` e o total vira enviados + falhas.
    """
    if job.status not in (
        ComunicadoJob.STATUS_CONCLUIDO,
        ComunicadoJob.STATUS_FALHOU,
    ):
        return 0
    with transaction.atomic():
        falhas = job.destinatarios.filter(
            status=ComunicadoDestinatario.STATUS_FALHOU
        )
        quantidade = falhas.count()
        if not quantidade:
            return 0
        falhas.update(
            status=ComunicadoDestinatario.STATUS_PENDENTE,
            erro="",
            enviado_em=None,
        )
        enviados = job.destinatarios.filter(
            status=ComunicadoDestinatario.STATUS_ENVIADO
        ).count()
        ComunicadoJob.objects.filter(pk=job.pk).update(
            status=ComunicadoJob.STATUS_PENDENTE,
            enviados=enviados,
            falhas=0,
            processados=enviados,
            total=enviados + quantidade,
            mensagem="",
            iniciado_em=None,
            concluido_em=None,
        )
    job.refresh_from_db()
    return quantidade


def job_como_dict(job):
    """JSON do job para a tela (status/progresso/reenvio)."""
    pronto = job.status in (
        ComunicadoJob.STATUS_CONCLUIDO,
        ComunicadoJob.STATUS_FALHOU,
    )
    detalhes = []
    if pronto and job.falhas:
        detalhes = list(
            job.destinatarios.filter(
                status=ComunicadoDestinatario.STATUS_FALHOU
            ).values("nome", "erro")[:10]
        )
    return {
        "job_id": job.pk,
        "status": job.status,
        "total": job.total,
        "processados": job.processados,
        "enviados": job.enviados,
        "falhas": job.falhas,
        "falhas_detalhe": detalhes,
        "mensagem": job.mensagem,
        "pronto": pronto,
        "pode_reenviar": bool(pronto and job.falhas),
    }


def envios_recentes(evento, limite=5):
    """Últimos comunicados do evento registrados na auditoria."""
    return list(
        RegistroAuditoria.objects.filter(
            evento=evento, acao=RegistroAuditoria.ACAO_ENVIAR_COMUNICADO
        ).order_by("-criado_em", "-id")[:limite]
    )
