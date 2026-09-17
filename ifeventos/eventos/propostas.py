"""Chamada de proposições: janela, grade de vagas e ciclo de vida da proposta.

O organizador abre um período e monta a grade de oferta (espaços + vagas com
dia, horário e capacidade). Durante a janela, qualquer participante cadastrado
propõe uma atividade escolhendo uma vaga livre; a proposta nasce como rascunho
pendente e a reserva da vaga acontece no envio.

Por que este módulo existe (e não só na view): as mesmas regras valem para a
tela do proponente, a do organizador e os testes — janela, reserva e conflitos
precisam de uma fonte única, como em `agenda.py` e `inscricoes.py`.

Quem "esconde" a proposta do público continua sendo `Atividade.publicada`
(programação, landing, .ics e PDF já filtram por ela); `Atividade.situacao`
apenas organiza o fluxo de aprovação.
"""

from types import SimpleNamespace

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import agenda
from .models import Atividade, ChamadaProposicoes, Espaco, Vaga, sem_acento


class PropostaBloqueada(ValidationError):
    """Proposta recusada por regra de negócio (janela, vaga ou conflito)."""


# ---------------------------------------------------------------------------
# Janela de proposições
# ---------------------------------------------------------------------------

def chamada_de(evento):
    """Chamada do evento (ou None). O OneToOne reverso levanta exceção quando
    não existe, então a busca é explícita."""
    if evento is None or not getattr(evento, "pk", None):
        return None
    return ChamadaProposicoes.objects.filter(evento_id=evento.pk).first()


def esta_aberta(evento, agora=None):
    chamada = chamada_de(evento)
    return bool(chamada and chamada.esta_aberta(agora))


def motivo_fechada(evento, agora=None):
    """Por que não está aberta — texto para a tela do proponente."""
    chamada = chamada_de(evento)
    if chamada is None:
        return "Este evento ainda não abriu chamada de propostas."
    agora = agora or timezone.now()
    if agora < chamada.inicio:
        abre = timezone.localtime(chamada.inicio).strftime("%d/%m/%Y às %H:%M")
        return f"A chamada de propostas abre em {abre}."
    if agora > chamada.fim:
        encerrou = timezone.localtime(chamada.fim).strftime("%d/%m/%Y às %H:%M")
        return f"A chamada de propostas encerrou em {encerrou}."
    return "A chamada de propostas está encerrada."


def situacao(evento, agora=None):
    """Frase curta do estado da chamada, para a tela do organizador."""
    chamada = chamada_de(evento)
    if chamada is None:
        return "Ainda não existe chamada para este evento."
    agora = agora or timezone.now()
    if chamada.esta_aberta(agora):
        fim = timezone.localtime(chamada.fim).strftime("%d/%m/%Y às %H:%M")
        return f"Aceitando propostas até {fim}."
    return motivo_fechada(evento, agora)


def chamadas_abertas(agora=None):
    """Chamadas abertas agora, de eventos que ainda não terminaram.

    É o que alimenta o banner da home: chamada aberta de um evento que já
    passou não interessa a ninguém.
    """
    agora = agora or timezone.now()
    return (
        ChamadaProposicoes.objects.filter(
            aberta=True,
            inicio__lte=agora,
            fim__gte=agora,
            evento__data_fim__gte=timezone.localdate(agora),
        )
        .select_related("evento")
        .order_by("fim")
    )


# ---------------------------------------------------------------------------
# Grade de oferta
# ---------------------------------------------------------------------------

def vagas_do_evento(evento, somente_livres=False):
    """Vagas da grade, na ordem (dia/espaço). `somente_livres` esconde as cheias."""
    vagas = list(evento.vagas.select_related("espaco").all())
    return [v for v in vagas if v.livre] if somente_livres else vagas


def vagas_livres(evento):
    return vagas_do_evento(evento, somente_livres=True)


def nomes_conhecidos():
    """Nomes de espaço que o sistema já usa (catálogo + locais das atividades).

    Serve de sugestão no cadastro de um espaço novo: reaproveitar o nome que a
    agenda já mostra é o que evita "Lab 1" e "Laboratório 1" virarem lugares
    diferentes. Aplica os apelidos (`AGENDA_ALIASES_LOCAL`) e não repete.
    """
    aliases = getattr(settings, "AGENDA_ALIASES_LOCAL", None) or {}
    nomes = {}

    def guardar(nome):
        limpo = " ".join(str(nome or "").split())
        if limpo:
            nomes.setdefault(sem_acento(limpo), limpo)

    for nome in Espaco.objects.values_list("nome", flat=True):
        guardar(nome)
    for local in Atividade.objects.exclude(local="").values_list("local", flat=True):
        for parte in (local or "").split(","):
            nome = parte.strip()
            guardar(aliases.get(nome, nome))
    return [nomes[chave] for chave in sorted(nomes)]


# ---------------------------------------------------------------------------
# Conflitos (mesmo espaço e/ou mesmo palestrante no mesmo horário)
# ---------------------------------------------------------------------------

def _lugares(local):
    """Lugares normalizados de um texto de local (aplica os apelidos da agenda)."""
    return set(agenda.locais_de(SimpleNamespace(local=local or "")))


def conflitos(evento, inicio, fim, local=None, palestrantes=None, ignorar=None,
              vaga=None):
    """Choques bloqueantes de uma proposta com a agenda do evento.

    Considera atividades publicadas, rascunhos do organizador e outras
    propostas (pendentes/aprovadas) — proposta rejeitada não ocupa nada.
    Devolve uma lista de `{"tipo": "espaco"|"palestrante", "rotulo", "atividade"}`.

    `vaga` é a vaga que a proposta vai ocupar: atividades NA MESMA VAGA não
    contam como choque de espaço (a capacidade da vaga é quem manda nisso), mas
    continuam valendo para o choque de palestrante — ninguém apresenta duas
    atividades ao mesmo tempo.
    """
    outras = (
        Atividade.objects.filter(
            evento=evento, data_hora_inicio__lt=fim, data_hora_fim__gt=inicio
        )
        .exclude(situacao=Atividade.SITUACAO_REJEITADA)
        .prefetch_related("palestrantes")
    )
    if getattr(ignorar, "pk", None):
        outras = outras.exclude(pk=ignorar.pk)

    meus_lugares = _lugares(local)
    meus_palestrantes = {p.pk for p in (palestrantes or []) if getattr(p, "pk", None)}

    avisos = []
    for outra in outras:
        mesma_vaga = vaga is not None and outra.vaga_id == vaga.pk
        if not mesma_vaga:
            for lugar in sorted(meus_lugares & _lugares(outra.local)):
                avisos.append({"tipo": "espaco", "rotulo": lugar, "atividade": outra})
        if meus_palestrantes:
            for pessoa in outra.palestrantes.all():
                if pessoa.pk in meus_palestrantes:
                    avisos.append(
                        {"tipo": "palestrante", "rotulo": str(pessoa), "atividade": outra}
                    )
    return avisos


def texto_do_conflito(avisos):
    """Mensagem legível para o proponente (o que chocou e com o quê)."""
    partes = []
    for aviso in avisos:
        atividade = aviso["atividade"]
        alvo = f"'{atividade.titulo}' ({atividade.quando_legivel})"
        if aviso["tipo"] == "espaco":
            partes.append(f"o espaço '{aviso['rotulo']}' já está ocupado por {alvo}")
        else:
            partes.append(f"{aviso['rotulo']} já tem atividade nesse horário: {alvo}")
    return "Conflito de agenda: " + "; ".join(partes) + "."


# ---------------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------------

def propor(usuario, evento, *, vaga, titulo, descricao, tipo=None,
           tipo_sugerido="", palestrantes=(), n_vagas=0,
           emite_certificado=False, imagem=None, agora=None):
    """Cria a proposta como rascunho pendente e reserva a vaga.

    A vaga é travada com `select_for_update` dentro da transação: é isso que faz
    "quem propõe primeiro leva" valer também com dois envios simultâneos.
    """
    agora = agora or timezone.now()
    chamada = chamada_de(evento)
    if not (chamada and chamada.esta_aberta(agora)):
        raise PropostaBloqueada(motivo_fechada(evento, agora))

    if vaga is None or vaga.evento_id != evento.pk:
        raise PropostaBloqueada("Escolha uma vaga da grade de oferta do evento.")

    dia = timezone.localtime(vaga.inicio).date()
    if not (evento.data_inicio <= dia <= evento.data_fim):
        raise PropostaBloqueada("Esta vaga está fora do período do evento.")

    with transaction.atomic():
        travada = (
            Vaga.objects.select_for_update()
            .select_related("espaco")
            .get(pk=vaga.pk)
        )
        if not travada.livre:
            raise PropostaBloqueada(
                f"A vaga de {travada} acabou de ser reservada por outra pessoa."
            )

        avisos = conflitos(
            evento, travada.inicio, travada.fim,
            local=travada.espaco.nome, palestrantes=palestrantes, vaga=travada,
        )
        if avisos:
            raise PropostaBloqueada(texto_do_conflito(avisos))

        atividade = Atividade.objects.create(
            evento=evento,
            titulo=(titulo or "").strip(),
            descricao=(descricao or "").strip(),
            local=travada.espaco.nome,
            tipo=tipo,
            tipo_sugerido=(tipo_sugerido or "").strip(),
            data_hora_inicio=travada.inicio,
            data_hora_fim=travada.fim,
            n_vagas=n_vagas or travada.espaco.capacidade,
            emite_certificado=emite_certificado,
            imagem=imagem,
            publicada=False,
            situacao=Atividade.SITUACAO_PENDENTE,
            proponente=usuario,
            vaga=travada,
        )
        if palestrantes:
            atividade.palestrantes.set(palestrantes)
        return atividade


def atualizar(atividade, *, vaga, titulo, descricao, tipo=None, tipo_sugerido="",
              palestrantes=None, n_vagas=0, emite_certificado=False, imagem=None,
              agora=None):
    """Edita a proposta do próprio autor (exige pendente + chamada aberta).

    Trocar de vaga é permitido e revalida tudo: a vaga é travada, checada como
    livre (descontando esta proposta) e os conflitos são refeitos.
    """
    if not atividade.pendente:
        raise PropostaBloqueada(
            "A proposta já foi decidida pelo organizador: só ele pode alterá-la."
        )
    evento = atividade.evento
    agora = agora or timezone.now()
    chamada = chamada_de(evento)
    if not (chamada and chamada.esta_aberta(agora)):
        raise PropostaBloqueada(motivo_fechada(evento, agora))

    alvo = vaga or atividade.vaga
    if alvo is None or alvo.evento_id != evento.pk:
        raise PropostaBloqueada("Escolha uma vaga da grade de oferta do evento.")

    with transaction.atomic():
        travada = (
            Vaga.objects.select_for_update().select_related("espaco").get(pk=alvo.pk)
        )
        if travada.propostas_ativas(ignorar=atividade).count() >= travada.capacidade:
            raise PropostaBloqueada(
                f"A vaga de {travada} acabou de ser reservada por outra pessoa."
            )

        avisos = conflitos(
            evento, travada.inicio, travada.fim,
            local=travada.espaco.nome, palestrantes=palestrantes,
            ignorar=atividade, vaga=travada,
        )
        if avisos:
            raise PropostaBloqueada(texto_do_conflito(avisos))

        atividade.vaga = travada
        atividade.local = travada.espaco.nome
        atividade.data_hora_inicio = travada.inicio
        atividade.data_hora_fim = travada.fim
        atividade.titulo = (titulo or "").strip()
        atividade.descricao = (descricao or "").strip()
        atividade.tipo = tipo
        atividade.tipo_sugerido = (tipo_sugerido or "").strip()
        atividade.n_vagas = n_vagas or travada.espaco.capacidade
        atividade.emite_certificado = bool(emite_certificado)
        if imagem:
            atividade.imagem = imagem
        atividade.save()
        if palestrantes is not None:
            atividade.palestrantes.set(palestrantes)
    return atividade


def _campos_decisao(atividade, tipo=None):
    campos = [
        "situacao", "publicada", "motivo_rejeicao", "decidida_em", "decidida_por",
    ]
    if tipo is not None:
        atividade.tipo = tipo
        campos.append("tipo")
    return campos


def aprovar(atividade, por, publicar=True, tipo=None):
    """Aprova a proposta e (por padrão) publica na programação.

    O proponente que se marcou como palestrante só ganha a flag
    `is_palestrante` aqui: enquanto a proposta é só uma intenção, não faz
    sentido ele aparecer na lista de palestrantes do sistema.
    """
    if not atividade.pendente:
        raise PropostaBloqueada("Esta proposta não está mais aguardando aprovação.")

    atividade.situacao = Atividade.SITUACAO_APROVADA
    atividade.publicada = bool(publicar)
    atividade.motivo_rejeicao = ""
    atividade.decidida_em = timezone.now()
    atividade.decidida_por = por
    atividade.save(update_fields=_campos_decisao(atividade, tipo))
    promover_palestrante(atividade)
    return atividade


def rejeitar(atividade, por, motivo):
    """Recusa a proposta (o motivo é obrigatório: é o retorno ao proponente).

    A vaga volta a ficar livre sozinha — `Vaga.ocupadas` conta apenas propostas
    pendentes ou aprovadas.
    """
    motivo = (motivo or "").strip()
    if not motivo:
        raise PropostaBloqueada(
            "Informe o motivo da rejeição — é o retorno que o proponente recebe."
        )
    atividade.situacao = Atividade.SITUACAO_REJEITADA
    atividade.publicada = False
    atividade.motivo_rejeicao = motivo
    atividade.decidida_em = timezone.now()
    atividade.decidida_por = por
    atividade.save(update_fields=_campos_decisao(atividade))
    return atividade


def cancelar(atividade):
    """Cancela a própria proposta (só enquanto pendente).

    Apaga a atividade: ela nunca foi pública e não tem inscrição — manter uma
    "rejeitada pelo próprio autor" só poluiria a lista do organizador.
    """
    if not atividade.pendente:
        raise PropostaBloqueada(
            "A proposta já foi decidida pelo organizador: só ele pode alterá-la."
        )
    atividade.delete()


def promover_palestrante(atividade):
    """Marca o proponente como palestrante quando ele se incluiu na atividade."""
    if not atividade.proponente_id:
        return
    if not atividade.palestrantes.filter(pk=atividade.proponente_id).exists():
        return
    proponente = atividade.proponente
    if not proponente.is_palestrante:
        proponente.is_palestrante = True
        proponente.save(update_fields=["is_palestrante"])


# ---------------------------------------------------------------------------
# Consultas para as telas
# ---------------------------------------------------------------------------

def minhas_propostas(usuario):
    return (
        Atividade.objects.filter(proponente=usuario)
        .select_related("evento", "tipo", "vaga", "vaga__espaco")
        .order_by("-date_created")
    )


def pendentes(eventos):
    """Propostas aguardando aprovação dos eventos informados."""
    return (
        Atividade.objects.filter(
            evento__in=eventos, situacao=Atividade.SITUACAO_PENDENTE
        )
        .select_related("evento", "tipo", "proponente", "vaga", "vaga__espaco")
        .order_by("data_hora_inicio", "id")
    )


def contagem_pendentes(eventos):
    return pendentes(eventos).count()


def eventos_do_organizador(usuario):
    """Eventos que este usuário gerencia (os mesmos do painel do organizador)."""
    from .models import Evento

    if usuario.is_superuser:
        return Evento.objects.all()
    return Evento.objects.filter(organizador=usuario)
