"""Checklist do arquivamento explícito de um evento.

Arquivar é decisão do organizador — a data encerra o evento, mas não o arquiva.
Antes de arquivar, a tela mostra o que está em aberto e o servidor revalida a
MESMA lista (nunca confia no formulário).

O que bloqueia é só o que impede o evento de estar "fechado para balanço":
atividade em rascunho e proposta sem decisão. Certificados, presenças e carga
horária entram como **aviso**: o organizador confirma a responsabilidade no
checkbox, mas não fica preso caso a emissão não seja obrigatória.

As regras de elegibilidade vêm de `eventos.certificados` (as mesmas da
emissão), então o checklist nunca divergirá do que os botões de emitir fazem.
"""

from dataclasses import dataclass

from django.urls import reverse

from . import certificados
from .models import Atividade, Certificado, CertificadoJob, Inscricao


@dataclass(frozen=True)
class ItemChecklist:
    """Uma linha do checklist: estado, se bloqueia e como resolver."""

    chave: str
    titulo: str
    detalhe: str = ""
    ok: bool = True
    bloqueante: bool = False
    url: str = ""
    acao: str = ""


def _item(chave, titulo, *, pendentes=0, sufixo="", ok_detalhe="", **extra):
    """Item padrão: `pendentes` > 0 vira detalhe; caso contrário, `ok_detalhe`."""
    ok = pendentes == 0
    detalhe = ok_detalhe if ok else f"{pendentes} {sufixo}".strip()
    return ItemChecklist(chave=chave, titulo=titulo, detalhe=detalhe, ok=ok, **extra)


def _url(evento, rota, *args):
    return reverse(rota, args=[evento.id, *args])


def _pendentes_de_atividade(evento):
    """Pessoas elegíveis ao certificado de alguma atividade sem certificado."""
    pendentes = 0
    for atividade in evento.atividades.filter(emite_certificado=True).only("id"):
        emitidos = Certificado.objects.filter(atividade=atividade).values_list(
            "participante_id", flat=True
        )
        pendentes += (
            certificados.participantes_da_atividade(atividade)
            .exclude(id__in=emitidos)
            .count()
        )
    return pendentes


def _pendentes_do_evento(evento):
    """Pessoas que cumprem o percentual mínimo e ainda não têm o certificado."""
    config = certificados.config_do_evento(evento)
    elegiveis = certificados.participantes_do_evento(evento, config)
    if not elegiveis.exists():
        return 0
    emitidos = Certificado.objects.filter(
        evento=evento, tipo=Certificado.TIPO_EVENTO
    ).values_list("participante_id", flat=True)
    return elegiveis.exclude(id__in=emitidos).count()


def _pendentes_por_funcao(evento):
    """Certificados de função (organizador, palestrante, equipe, comissão)."""
    from .models import FUNCAO_CHOICES

    pendentes = 0
    for funcao, _rotulo in FUNCAO_CHOICES:
        elegiveis = certificados.participantes_da_funcao(evento, funcao)
        if not elegiveis.exists():
            continue
        emitidos = Certificado.objects.filter(
            evento=evento, tipo=Certificado.TIPO_FUNCAO, funcao=funcao
        ).values_list("participante_id", flat=True)
        pendentes += elegiveis.exclude(id__in=emitidos).count()
    return pendentes


def checklist(evento):
    """Lista completa do checklist, na ordem em que aparece na tela."""
    itens = [
        _item(
            "atividades_rascunho",
            "Atividades publicadas",
            pendentes=evento.atividades.filter(publicada=False).count(),
            sufixo="rascunho(s) sem publicar",
            ok_detalhe="Todas as atividades estão publicadas.",
            bloqueante=True,
            url=_url(evento, "organizador:atividades_evento"),
            acao="Publicar ou excluir",
        ),
        _item(
            "propostas_pendentes",
            "Propostas de atividades",
            pendentes=evento.atividades.filter(
                situacao=Atividade.SITUACAO_PENDENTE
            ).count(),
            sufixo="aguardando decisão",
            ok_detalhe="Nenhuma proposta pendente.",
            bloqueante=True,
            url=_url(evento, "organizador:propostas_pendentes"),
            acao="Revisar fila",
        ),
        _item(
            "emissao_andamento",
            "Emissão de certificados",
            pendentes=CertificadoJob.objects.filter(
                evento=evento,
                status__in=[
                    CertificadoJob.STATUS_PENDENTE,
                    CertificadoJob.STATUS_PROCESSANDO,
                ],
            ).count(),
            sufixo="envio(s) ainda em andamento",
            ok_detalhe="Nenhuma emissão em andamento.",
            url=_url(evento, "organizador:certificado_config", "evento"),
            acao="Acompanhar",
        ),
    ]

    if evento.terminou:
        itens += [
            _item(
                "certificados_atividade",
                "Certificados das atividades",
                pendentes=_pendentes_de_atividade(evento),
                sufixo="pessoa(s) elegível(is) sem certificado",
                ok_detalhe="Todos os certificados de atividade foram emitidos.",
                url=_url(evento, "organizador:certificado_config", "atividades"),
                acao="Emitir pendentes",
            ),
            _item(
                "certificados_evento",
                "Certificados do evento",
                pendentes=_pendentes_do_evento(evento),
                sufixo="pessoa(s) elegível(is) sem certificado",
                ok_detalhe="Todos os certificados do evento foram emitidos.",
                url=_url(evento, "organizador:certificado_config", "evento"),
                acao="Emitir do evento",
            ),
            _item(
                "certificados_funcao",
                "Certificados de função",
                pendentes=_pendentes_por_funcao(evento),
                sufixo="certificado(s) de função não emitido(s)",
                ok_detalhe="Nenhum certificado de função pendente.",
                url=_url(evento, "organizador:certificado_config", "organizador"),
                acao="Emitir por função",
            ),
        ]

    tem_publicadas = evento.atividades.filter(publicada=True).exists()
    itens += [
        ItemChecklist(
            chave="atividades_publicadas",
            titulo="Evento com programação",
            detalhe=(
                "Há atividades publicadas."
                if tem_publicadas
                else "O evento não tem atividade publicada."
            ),
            ok=tem_publicadas,
            url=_url(evento, "organizador:atividades_evento"),
            acao="Criar atividade",
        ),
        _item(
            "presencas_pendentes",
            "Presenças conferidas",
            pendentes=Inscricao.objects.filter(
                atividade__evento=evento, confirmada=False
            ).count(),
            sufixo="inscrição(ões) sem presença confirmada",
            ok_detalhe="Todas as inscrições têm presença confirmada.",
            url=_url(evento, "organizador:relatorio_inscricoes"),
            acao="Conferir inscrições",
        ),
        _item(
            "carga_horaria",
            "Carga horária dos certificados",
            pendentes=(
                0
                if evento.carga_horaria
                else evento.atividades.filter(
                    emite_certificado=True, carga_horaria__isnull=True
                ).count()
            ),
            sufixo="atividade(s) que emitem certificado sem carga horária",
            ok_detalhe="Carga horária definida.",
            url=_url(evento, "organizador:atividades_evento"),
            acao="Revisar atividades",
        ),
    ]
    return itens


def itens_bloqueantes(evento):
    """Itens que impedem o arquivamento agora."""
    return [item for item in checklist(evento) if item.bloqueante and not item.ok]


def pode_encerrar(evento):
    return not itens_bloqueantes(evento)


def retrato_para_auditoria(evento, itens=None):
    """O que estava em aberto no momento do arquivamento (rastreabilidade)."""
    itens = checklist(evento) if itens is None else itens
    return {
        "data_fim": evento.data_fim.isoformat(),
        "terminou": evento.terminou,
        "pendentes": {
            item.chave: item.detalhe for item in itens if not item.ok
        },
    }
