"""Emissão assíncrona de certificados: fila em banco + processamento.

O clique do organizador cria um `CertificadoJob` (rápido) e a tela acompanha o
progresso por AJAX polling. Um worker dedicado (`manage.py processar_certificados`)
reivindica e processa um job por vez. Lotes pequenos são processados na hora
(`LIMITE_SINCRONO`), sem abrir modal.

Sem Redis/Celery: a própria tabela `CertificadoJob` é a fila.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import auditoria, certificados
from .models import CertificadoJob, Participante, RegistroAuditoria

logger = logging.getLogger(__name__)

# Padrão do limite síncrono (pode ser ajustado por `settings.CERTIFICADOS_LIMITE_SINCRONO`).
LIMITE_SINCRONO = 3
# Itens processados por atualização de progresso (e por chamada de `emitir_lote`).
TAM_LOTE = 5
# Job preso em "processando" por mais que isto é reciclado para "pendente".
MINUTOS_PRESO = 30


def _lotes(job):
    """Gera lotes `(participantes, atividade, evento, funcao)` — mesmo alvo por lote.

    Em "todas as atividades" cada atividade é um lote; nos demais escopos há um
    único alvo. `participante_id` restringe a uma pessoa (emissão individual).
    """
    evento = job.evento
    funcao = job.funcao or None

    if job.escopo == CertificadoJob.ESCOPO_TODAS:
        for atividade in evento.atividades.filter(emite_certificado=True).order_by("id"):
            pessoas = certificados.participantes_da_atividade(atividade)
            if job.participante_id:
                pessoas = pessoas.filter(id=job.participante_id)
            yield list(pessoas), atividade, None, None
        return

    if job.escopo == CertificadoJob.ESCOPO_ATIVIDADE:
        pessoas = certificados.participantes_da_atividade(job.atividade)
        alvo = (job.atividade, None, None)
    elif job.escopo == CertificadoJob.ESCOPO_EVENTO:
        pessoas = certificados.participantes_do_evento(
            evento, certificados.config_do_evento(evento)
        )
        alvo = (None, evento, None)
    elif job.escopo == CertificadoJob.ESCOPO_FUNCAO:
        pessoas = certificados.participantes_da_funcao(evento, funcao)
        alvo = (None, evento, funcao)
    else:
        pessoas = Participante.objects.none()
        alvo = (None, None, None)

    if job.participante_id:
        pessoas = pessoas.filter(id=job.participante_id)
    yield list(pessoas), alvo[0], alvo[1], alvo[2]


def _total(job):
    return sum(len(pessoas) for pessoas, *_ in _lotes(job))


def enfileirar_job(*, escopo, evento, atividade=None, funcao=None, participante=None, criado_por=None):
    """Cria o job com `total` já calculado. Devolve o `CertificadoJob`."""
    job = CertificadoJob.objects.create(
        escopo=escopo,
        evento=evento,
        atividade=atividade,
        funcao=funcao or "",
        participante=participante,
        criado_por=criado_por,
    )
    job.total = _total(job)
    job.save(update_fields=["total"])
    return job


def processar_job(job):
    """Processa o job em blocos, atualizando o progresso. Devolve o job."""
    CertificadoJob.objects.filter(pk=job.pk).update(
        status=CertificadoJob.STATUS_PROCESSANDO, iniciado_em=timezone.now()
    )
    total = _total(job)
    processados = gerados = ja_emitidos = 0
    falhas = []
    for pessoas, atividade, evento, funcao in _lotes(job):
        for i in range(0, len(pessoas), TAM_LOTE):
            bloco = pessoas[i : i + TAM_LOTE]
            g, j, f = certificados.emitir_lote(
                bloco, atividade=atividade, evento=evento, funcao=funcao
            )
            gerados += len(g)
            ja_emitidos += len(j)
            falhas += f
            processados += len(bloco)
            CertificadoJob.objects.filter(pk=job.pk).update(
                total=total,
                processados=processados,
                gerados=gerados,
                ja_emitidos=ja_emitidos,
                falhas=falhas,
            )

    mensagem = f"{gerados} gerado(s), {ja_emitidos} já existente(s)"
    if falhas:
        mensagem += f", {len(falhas)} falha(s)"
    CertificadoJob.objects.filter(pk=job.pk).update(
        status=CertificadoJob.STATUS_CONCLUIDO,
        mensagem=mensagem,
        concluido_em=timezone.now(),
    )
    _auditar(job, gerados, falhas)
    job.refresh_from_db()
    return job


def _auditar(job, gerados, falhas):
    auditoria.registrar(
        acao=RegistroAuditoria.ACAO_EMITIR_CERTIFICADO,
        objeto=job.evento,
        evento=job.evento,
        resumo=f"Emitiu {gerados} certificado(s) ({job.escopo})",
        detalhes={
            "tipo": job.escopo,
            "funcao": job.funcao,
            "gerados": gerados,
            "falhas": falhas,
        },
    )


def iniciar_job(*, escopo, evento, atividade=None, funcao=None, participante=None, criado_por=None):
    """Enfileira e, se o lote for pequeno, processa na hora.

    Devolve `(job, pronto)` — `pronto=True` quando já foi processado inline.
    """
    job = enfileirar_job(
        escopo=escopo, evento=evento, atividade=atividade, funcao=funcao,
        participante=participante, criado_por=criado_por,
    )
    # Limite por evento (se definido) sobrepõe o padrão do sistema.
    limite = evento.certificado_limite_sincrono
    if limite is None:
        limite = getattr(settings, "CERTIFICADOS_LIMITE_SINCRONO", LIMITE_SINCRONO)
    if job.total <= limite:
        processar_job(job)
        return job, True
    return job, False


def processar_proximo_job():
    """Reivindica e processa o próximo job pendente (claim atômico).

    Devolve o `CertificadoJob` processado, ou None se não havia pendente.
    """
    with transaction.atomic():
        job = (
            CertificadoJob.objects.select_for_update(skip_locked=True)
            .filter(status=CertificadoJob.STATUS_PENDENTE)
            .order_by("criado_em")
            .first()
        )
        if job is None:
            return None
        CertificadoJob.objects.filter(pk=job.pk).update(
            status=CertificadoJob.STATUS_PROCESSANDO, iniciado_em=timezone.now()
        )

    try:
        processar_job(job)
    except Exception:
        logger.exception("certificados: job %s falhou", job.pk)
        CertificadoJob.objects.filter(pk=job.pk).update(
            status=CertificadoJob.STATUS_FALHOU,
            mensagem="Erro ao processar o job.",
            concluido_em=timezone.now(),
        )
    return job


def reciclar_presos():
    """Devolve jobs presos em `processando` (worker caiu) para `pendente`."""
    limite = timezone.now() - timedelta(minutes=MINUTOS_PRESO)
    return CertificadoJob.objects.filter(
        status=CertificadoJob.STATUS_PROCESSANDO, iniciado_em__lt=limite
    ).update(status=CertificadoJob.STATUS_PENDENTE, iniciado_em=None)


def job_como_dict(job):
    """JSON do job para a tela (status/progresso)."""
    pronto = job.status in (
        CertificadoJob.STATUS_CONCLUIDO,
        CertificadoJob.STATUS_FALHOU,
    )
    return {
        "job_id": job.pk,
        "status": job.status,
        "total": job.total,
        "processados": job.processados,
        "gerados": job.gerados,
        "ja_emitidos": job.ja_emitidos,
        "falhas": job.falhas or [],
        "mensagem": job.mensagem,
        "pronto": pronto,
    }
