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

import re
from datetime import datetime, time, timedelta
from types import SimpleNamespace

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import agenda
from .models import (
    Atividade, ChamadaProposicoes, Espaco, PalestranteSugerido, Vaga, sem_acento,
)


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

# Um bloco de horário da grade: `08:00-10:00` (aceita `-`, `–` e espaços).
BLOCO_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})$")


def parse_blocos(texto):
    """Converte os blocos digitados (um por linha) em `[(time, time), …]`.

    Aceita vírgula no lugar de quebra de linha e ignora linhas vazias.
    Levanta `ValueError` com a linha problemática — quem chama (formulário ou
    API) mostra a mensagem no campo certo.
    """
    blocos, vistas = [], set()
    for numero, linha in enumerate((texto or "").replace(",", "\n").splitlines(), start=1):
        linha = linha.strip()
        if not linha:
            continue
        achado = BLOCO_RE.match(linha)
        if not achado:
            raise ValueError(
                f"Linha {numero}: use o formato HH:MM-HH:MM (ex.: 08:00-10:00)."
            )
        hora1, min1, hora2, min2 = (int(valor) for valor in achado.groups())
        try:
            inicio, fim = time(hora1, min1), time(hora2, min2)
        except ValueError:
            raise ValueError(f"Linha {numero}: horário inválido.")
        if fim <= inicio:
            raise ValueError(f"Linha {numero}: o término precisa ser depois do início.")
        if (inicio, fim) not in vistas:
            vistas.add((inicio, fim))
            blocos.append((inicio, fim))
    if not blocos:
        raise ValueError("Informe pelo menos um bloco de horário.")
    return blocos


def validar_vaga(evento, *, espaco, inicio, fim, capacidade, instancia=None):
    """Regras de uma vaga, compartilhadas pela TELA (`VagaForm`) e pela API.

    Devolve `{campo: [mensagem]}` — quem chama decide como mostrar o erro.
    `instancia` é a vaga sendo editada (para não acusá-la de duplicar a si
    mesma e para as travas de "já tem proposta").
    """
    erros = {}

    def erro(campo, mensagem):
        erros.setdefault(campo, []).append(mensagem)

    if inicio and fim and fim <= inicio:
        erro("fim", "O término precisa ser depois do início.")
        return erros

    if inicio and evento is not None:
        dia = timezone.localtime(inicio).date()
        if not (evento.data_inicio <= dia <= evento.data_fim):
            erro(
                "inicio",
                "O dia da vaga precisa estar dentro do período do evento.",
            )

    if espaco and inicio and fim:
        repetida = Vaga.objects.filter(espaco=espaco, inicio=inicio, fim=fim)
        if instancia is not None and instancia.pk:
            repetida = repetida.exclude(pk=instancia.pk)
        if repetida.exists():
            erro("inicio", "Já existe uma vaga deste espaço nessa janela.")

    if instancia is not None and instancia.pk and instancia.tem_propostas_ativas:
        ocupadas = instancia.ocupadas
        if capacidade is not None and capacidade < ocupadas:
            erro(
                "capacidade",
                f"Esta vaga tem {ocupadas} proposta(s) ativa(s): a capacidade "
                "não pode ficar menor que isso.",
            )
        for campo, novo in (("espaco", espaco), ("inicio", inicio), ("fim", fim)):
            if novo is not None and novo != getattr(instancia, campo):
                erro(
                    campo,
                    "Esta vaga já tem proposta: espaço e horário ficam "
                    "travados (a reserva da proposta depende deles).",
                )
    return erros


def vagas_do_evento(evento, somente_livres=False):
    """Vagas da grade, na ordem (dia/espaço). `somente_livres` esconde as cheias."""
    vagas = list(evento.vagas.select_related("espaco").all())
    return [v for v in vagas if v.livre] if somente_livres else vagas


def vagas_livres(evento):
    return vagas_do_evento(evento, somente_livres=True)


def grade_de_propostas(evento, usuario=None):
    """TODAS as vagas com as propostas ativas — o mapa de ocupação da grade.

    Diferente de `vagas_livres`, as vagas já reservadas também aparecem: é o que
    deixa o proponente ver, na própria tela, o que já foi proposto para aquele
    horário/espaço e evitar conflito. `rejeitada` não ocupa (a vaga está livre),
    então só pendente/aprovada (e atividade criada pelo organizador) entram.

    Devolve uma lista de dicts, na ordem da grade:
        {"vaga": Vaga, "propostas": [Atividade, ...], "minha": bool}

    `minha` marca a vaga que tem proposta do próprio usuário (destaque na tela).
    """
    vagas = list(
        Vaga.objects.filter(evento=evento)
        .select_related("espaco")
        .order_by("inicio", "espaco__nome")
    )
    por_vaga = {}
    propostas = (
        Atividade.objects.filter(evento=evento, vaga__isnull=False)
        .exclude(situacao=Atividade.SITUACAO_REJEITADA)
        .select_related("proponente", "tipo")
        .prefetch_related("palestrantes")
    )
    for proposta in propostas:
        por_vaga.setdefault(proposta.vaga_id, []).append(proposta)

    meu_id = getattr(usuario, "pk", None)
    return [
        {
            "vaga": vaga,
            "propostas": por_vaga.get(vaga.pk, []),
            "minha": any(
                proposta.proponente_id == meu_id
                for proposta in por_vaga.get(vaga.pk, [])
            ),
        }
        for vaga in vagas
    ]


def grade_em_json(slots):
    """Versão serializável de `grade_de_propostas` — é o que a grade do JS lê.

    `ocupadas` vem do tamanho da lista (e não de `Vaga.ocupadas`) para não
    disparar uma consulta por vaga: `propostas_ativas` é exatamente este
    conjunto (tudo que aponta para a vaga, menos a rejeitada).
    """
    return [
        {
            "valor": slot["vaga"].pk,
            "espaco": slot["vaga"].espaco.nome,
            "inicio": slot["vaga"].inicio.isoformat(),
            "fim": slot["vaga"].fim.isoformat(),
            "capacidade": slot["vaga"].capacidade,
            "ocupadas": len(slot["propostas"]),
            "livre": len(slot["propostas"]) < slot["vaga"].capacidade,
            "minha": slot["minha"],
            "propostas": [
                {
                    "titulo": proposta.titulo,
                    "proponente": (
                        proposta.proponente.get_full_name()
                        or proposta.proponente.email
                    ) if proposta.proponente else "Organização",
                    "palestrantes": [
                        str(pessoa) for pessoa in proposta.palestrantes.all()
                    ],
                    "situacao": proposta.situacao,
                }
                for proposta in slot["propostas"]
            ],
        }
        for slot in slots
    ]


# Evento muito longo geraria uma lista de dias impraticável no formulário.
DIAS_MAXIMOS_NO_FORM = 60

# Visões do campo de vaga no formulário da proposta (alternador Lista/Grade).
VISTAS_VAGA = [
    {"valor": "lista", "rotulo": "Lista", "icone": "fa-solid fa-list"},
    {"valor": "grade", "rotulo": "Grade", "icone": "fa-solid fa-table-cells"},
]


def dias_do_evento(evento, limite=DIAS_MAXIMOS_NO_FORM):
    """Dias do evento como `(valor ISO, rótulo curto)` para os formulários."""
    if evento is None or not getattr(evento, "pk", None):
        return []
    total = (evento.data_fim - evento.data_inicio).days
    if total < 0:
        return []
    dias = []
    for indice in range(min(total, limite - 1) + 1):
        dia = evento.data_inicio + timedelta(days=indice)
        rotulo = f"{agenda.DIAS_SEMANA[dia.weekday()]} {dia.strftime('%d/%m')}"
        dias.append((dia.isoformat(), rotulo))
    return dias


def gerar_grade(evento, dias, blocos, espacos, capacidade=None):
    """Cria vagas em lote: dias × blocos × espaços, sem duplicar.

    `dias` são `date`, `blocos` é uma lista de `(time, time)` e `espacos` são
    instâncias de `Espaco`. Vaga que já existe com o MESMO espaço+início+fim é
    pulada e contada em "existentes" — a constraint `unique_vaga_espaco_janela`
    é global (a sala não pode ter duas vagas idênticas), então rodar o gerador
    de novo não duplica nada.

    `capacidade=None` usa a capacidade sugerida de cada `Espaco`; um valor
    explícito vale para todas as vagas criadas.

    Devolve `{"criadas": int, "existentes": int}`.
    """
    fusos = timezone.get_current_timezone()
    desejadas = {}
    for dia in dias or []:
        for inicio, fim in blocos or []:
            for espaco in espacos or []:
                chave = (
                    espaco.pk,
                    timezone.make_aware(datetime.combine(dia, inicio), fusos),
                    timezone.make_aware(datetime.combine(dia, fim), fusos),
                )
                desejadas[chave] = espaco

    if not desejadas:
        return {"criadas": 0, "existentes": 0}

    existentes = set(
        Vaga.objects.filter(espaco__in=list(espacos)).values_list(
            "espaco_id", "inicio", "fim"
        )
    )
    novas = [
        Vaga(evento=evento, espaco=espaco, inicio=inicio, fim=fim,
             capacidade=capacidade if capacidade is not None else espaco.capacidade)
        for (espaco_id, inicio, fim), espaco in desejadas.items()
        if (espaco_id, inicio, fim) not in existentes
    ]
    Vaga.objects.bulk_create(novas)
    return {"criadas": len(novas), "existentes": len(desejadas) - len(novas)}


def propostas_ativas_de(usuario, evento):
    """Propostas que ainda contam para o limite (pendentes ou aprovadas).

    Rejeitada e cancelada não contam: a pessoa pode propor de novo.
    """
    if usuario is None or not getattr(usuario, "pk", None):
        return Atividade.objects.none()
    return Atividade.objects.filter(
        evento=evento,
        proponente=usuario,
        situacao__in=[Atividade.SITUACAO_PENDENTE, Atividade.SITUACAO_APROVADA],
    )


def limite_por_proponente():
    """Limite configurado por evento (0 = sem limite)."""
    return int(getattr(settings, "MAX_PROPOSTAS_POR_PROPONENTE", 0) or 0)


def restantes_para_propor(usuario, evento):
    """Quantas propostas ainda cabem para esta pessoa (None = sem limite)."""
    limite = limite_por_proponente()
    if limite <= 0:
        return None
    return max(0, limite - propostas_ativas_de(usuario, evento).count())


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
           emite_certificado=False, imagem=None,
           recursos_necessarios="", consentimento_voluntario=False,
           sugestoes_palestrantes=(), agora=None):
    """Cria a proposta como rascunho pendente e reserva a vaga.

    A vaga é travada com `select_for_update` dentro da transação: é isso que faz
    "quem propõe primeiro leva" valer também com dois envios simultâneos.
    """
    agora = agora or timezone.now()
    chamada = chamada_de(evento)
    if not (chamada and chamada.esta_aberta(agora)):
        raise PropostaBloqueada(motivo_fechada(evento, agora))

    restantes = restantes_para_propor(usuario, evento)
    if restantes is not None and restantes <= 0:
        raise PropostaBloqueada(
            f"Você já tem {propostas_ativas_de(usuario, evento).count()} propostas "
            f"neste evento (limite de {limite_por_proponente()}). "
            "Cancele uma para propor outra."
        )

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
            recursos_necessarios=(recursos_necessarios or "").strip(),
            consentimento_voluntario=bool(consentimento_voluntario),
        )
        if palestrantes:
            atividade.palestrantes.set(palestrantes)
        _salvar_sugestoes_palestrantes(atividade, sugestoes_palestrantes, usuario)

        # Aviso só DEPOIS do commit: se a transação voltar atrás, ninguém
        # recebe e-mail de uma proposta que não existe.
        transaction.on_commit(lambda: avisar_proposta_nova(atividade))
        transaction.on_commit(lambda: avisar_mudanca(evento))
        return atividade


def _salvar_sugestoes_palestrantes(atividade, sugestoes, usuario):
    """Cria os `PalestranteSugerido` da proposta.

    `sugestoes` é uma lista de dicts `{nome, email, telefone}`; ignora entradas
    sem nome. Sugestão cujo e-mail já pertence a um participante NÃO vira
    sugestão: a pessoa é marcada como palestrante escolhido (evita que o
    organizador receba alguém já cadastrado para criar de novo).
    """
    from .models import Participante

    for dado in sugestoes or []:
        nome = " ".join(str((dado or {}).get("nome") or "").split())
        if not nome:
            continue
        email = (str(dado.get("email") or "").strip()).lower()
        if email:
            existente = Participante.objects.filter(email__iexact=email).first()
            if existente:
                if existente.pk != getattr(usuario, "pk", None):
                    atividade.palestrantes.add(existente)
                continue
        PalestranteSugerido.objects.create(
            atividade=atividade,
            nome=nome[:255],
            email=email[:255],
            telefone=str(dado.get("telefone") or "").strip()[:40],
            criado_por=usuario,
        )


def _substituir_sugestoes_palestrantes(atividade, sugestoes, usuario):
    """Sincroniza as sugestões com o que o autor mandou no formulário (edição).

    Remove sugestões que saíram da tela e cria as novas (não tenta fazer diff
    por id: o frontend envia a lista final).
    """
    atividade.palestrantes_sugeridos.all().delete()
    _salvar_sugestoes_palestrantes(atividade, sugestoes, usuario)


def atualizar(atividade, *, vaga, titulo, descricao, tipo=None, tipo_sugerido="",
              palestrantes=None, n_vagas=0, emite_certificado=False, imagem=None,
              recursos_necessarios="", consentimento_voluntario=False,
              sugestoes_palestrantes=None, agora=None):
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
        atividade.recursos_necessarios = (recursos_necessarios or "").strip()
        atividade.consentimento_voluntario = bool(consentimento_voluntario)
        if imagem:
            atividade.imagem = imagem
        atividade.save()
        if palestrantes is not None:
            atividade.palestrantes.set(palestrantes)
        if sugestoes_palestrantes is not None:
            _substituir_sugestoes_palestrantes(
                atividade, sugestoes_palestrantes, atividade.proponente
            )
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
    transaction.on_commit(lambda: avisar_decisao(atividade, aprovada=True))
    transaction.on_commit(lambda: avisar_mudanca(atividade.evento))
    return atividade


def rejeitar(atividade, por, motivo):
    """Recusa a proposta PENDENTE (o motivo é obrigatório: é o retorno ao proponente).

    A decisão é terminal, como em `aprovar`: rejeitar o que já foi decidido
    trocaria um "aprovada" por um "rejeitada" em silêncio — quem quer tirar uma
    atividade já aprovada exclui a atividade, não a proposta.

    A vaga volta a ficar livre sozinha — `Vaga.ocupadas` conta apenas propostas
    pendentes ou aprovadas.
    """
    if not atividade.pendente:
        raise PropostaBloqueada("Esta proposta não está mais aguardando aprovação.")
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
    transaction.on_commit(lambda: avisar_decisao(atividade, aprovada=False))
    transaction.on_commit(lambda: avisar_mudanca(atividade.evento))
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
    evento = atividade.evento  # guardado antes: depois do delete não há linha
    atividade.delete()
    transaction.on_commit(lambda: avisar_mudanca(evento))


def remover(atividade):
    """Remove a proposta em qualquer situação — ação do organizador.

    `cancelar` é o autor desistindo de algo ainda pendente; aqui quem decide já
    pode apagar a proposta mesmo depois da decisão (é o mesmo efeito de excluir
    a atividade pela programação, que sempre foi permitido). Avisa a mudança
    para quem acompanha a grade.
    """
    evento = atividade.evento  # guardado antes: depois do delete não há linha
    atividade.delete()
    transaction.on_commit(lambda: avisar_mudanca(evento))


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


def cadastrar_sugerido(sugestao, *, nome=None, email=None, telefone=None):
    """Converte um `PalestranteSugerido` em palestrante da atividade.

    Se o e-mail já pertencer a um participante, vincula ao existente (sem
    duplicar); senão cria um Participante com `is_palestrante=True`. Em ambos
    os casos adiciona à atividade e marca a sugestão como convertida.
    """
    from .models import Participante

    if sugestao.participante_id:
        return sugestao

    email_limpo = (email or sugestao.email or "").strip().lower()
    if not email_limpo:
        raise PropostaBloqueada(
            "Informe o e-mail do palestrante sugerido para cadastrá-lo."
        )

    atividade = sugestao.atividade
    nome_limpo = " ".join((nome or sugestao.nome or "").split()) or "Palestrante"

    participante = Participante.objects.filter(email__iexact=email_limpo).first()
    if participante is None:
        partes = nome_limpo.split(" ", 1)
        participante = Participante(
            email=email_limpo,
            username=email_limpo,
            first_name=partes[0],
            last_name=partes[1] if len(partes) > 1 else "",
            telefone=(telefone or sugestao.telefone or "").strip(),
            is_palestrante=True,
        )
        participante.set_unusable_password()
        participante.save()
        # Pré-carga: se o e-mail estiver na planilha, completa os metadados que
        # faltam (a sugestão do proponente continua tendo prioridade).
        from . import roster

        roster.completar_do_roster(participante)

    if not participante.is_palestrante:
        participante.is_palestrante = True
        participante.save(update_fields=["is_palestrante"])

    atividade.palestrantes.add(participante)
    sugestao.participante = participante
    sugestao.nome = nome_limpo
    sugestao.email = email_limpo
    sugestao.telefone = (telefone or sugestao.telefone or "").strip()
    sugestao.save()
    return sugestao


# ---------------------------------------------------------------------------
# Avisos por e-mail (best-effort: nunca quebram a ação principal)
# ---------------------------------------------------------------------------

def avisar_proposta_nova(atividade):
    """Manda para o organizador do evento a proposta que acabou de chegar."""
    from . import emails  # import local: evita ciclo com models/settings

    if not emails.notificar_email_ligado():
        return False

    organizador = atividade.evento.organizador
    if organizador is None or not getattr(organizador, "email", ""):
        return False

    return emails.enviar(
        assunto=f"Nova proposta: {atividade.titulo}",
        destinatarios=[organizador.email],
        template="emails/proposta_nova.txt",
        contexto={
            "atividade": atividade,
            "evento": atividade.evento,
            "proponente": atividade.proponente,
            "url": emails.site_url(
                reverse("organizador:propostas_pendentes", args=[atividade.evento_id])
            ),
        },
    )


def avisar_mudanca(evento):
    """Avisa as telas abertas que a fila de propostas mudou.

    Payload mínimo de propósito (id do evento + quantos aguardam): este socket
    emite para todo mundo, então nada de título/proponente aqui. Import local de
    `services`, como em `crachas.py`, para não criar ciclo entre os módulos.
    """
    from .services import notify_socketio

    return notify_socketio("propostas_atualizadas", {
        "evento_id": evento.pk,
        "pendentes": contagem_pendentes([evento]),
    })


def avisar_decisao(atividade, aprovada):
    """Manda para o proponente o resultado da avaliação (com o motivo)."""
    from . import emails

    if not emails.notificar_email_ligado():
        return False

    proponente = atividade.proponente
    if proponente is None or not getattr(proponente, "email", ""):
        return False

    return emails.enviar(
        assunto=("Proposta aprovada" if aprovada else "Proposta não aprovada")
        + f": {atividade.titulo}",
        destinatarios=[proponente.email],
        template=(
            "emails/proposta_aprovada.txt" if aprovada
            else "emails/proposta_rejeitada.txt"
        ),
        contexto={
            "atividade": atividade,
            "evento": atividade.evento,
            "url": emails.site_url(reverse("participante:minhas_propostas")),
        },
    )


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


def resumo(evento):
    """Números da chamada para o painel do organizador.

    Função pura (só consulta) para a tela e os testes contarem a mesma coisa:
    indicadores, propostas por situação, ocupação por espaço e vagas livres.
    """
    vagas = list(evento.vagas.select_related("espaco").all())
    propostas = list(
        Atividade.objects.filter(evento=evento, proponente__isnull=False)
        .select_related("proponente", "vaga", "vaga__espaco")
        .order_by("-date_created", "-id")
    )
    total = len(propostas)

    def quantas(situacao):
        return sum(1 for proposta in propostas if proposta.situacao == situacao)

    pendentes = quantas(Atividade.SITUACAO_PENDENTE)
    aprovadas = quantas(Atividade.SITUACAO_APROVADA)
    rejeitadas = quantas(Atividade.SITUACAO_REJEITADA)
    decididas = aprovadas + rejeitadas

    def fatia(quantidade):
        return round(100 * quantidade / total) if total else 0

    total_vagas = len(vagas)
    livres = [vaga for vaga in vagas if vaga.livre]
    ocupadas = total_vagas - len(livres)

    kpis = [
        {"rotulo": "Propostas", "valor": total, "icone": "fa-solid fa-lightbulb"},
        {"rotulo": "Aguardando", "valor": pendentes,
         "icone": "fa-solid fa-hourglass-half"},
        {"rotulo": "Aprovadas", "valor": aprovadas,
         "icone": "fa-solid fa-circle-check"},
        {"rotulo": "Rejeitadas", "valor": rejeitadas,
         "icone": "fa-solid fa-circle-xmark"},
        {"rotulo": "Taxa de aprovação",
         "valor": round(100 * aprovadas / decididas) if decididas else 0,
         "sufixo": "%", "icone": "fa-solid fa-percent"},
        {"rotulo": "Vagas na grade", "valor": total_vagas,
         "icone": "fa-regular fa-clock"},
        {"rotulo": "Vagas livres", "valor": len(livres),
         "icone": "fa-solid fa-lock-open"},
        {"rotulo": "Ocupação da grade",
         "valor": round(100 * ocupadas / total_vagas) if total_vagas else 0,
         "sufixo": "%", "icone": "fa-solid fa-gauge-high"},
    ]

    por_status = [
        {"rotulo": "Aguardando aprovação", "total": pendentes,
         "percentual": fatia(pendentes), "cor": "#f59e0b"},
        {"rotulo": "Aprovadas", "total": aprovadas,
         "percentual": fatia(aprovadas), "cor": "var(--accent)"},
        {"rotulo": "Rejeitadas", "total": rejeitadas,
         "percentual": fatia(rejeitadas), "cor": "#b91c1c"},
    ]

    por_espaco = {}
    for vaga in vagas:
        bloco = por_espaco.setdefault(
            vaga.espaco_id,
            {"espaco": vaga.espaco, "total": 0, "livres": 0, "vagas": []},
        )
        bloco["total"] += 1
        if vaga.livre:
            bloco["livres"] += 1
        bloco["vagas"].append({
            "vaga": vaga,
            "proposta": next(
                (
                    proposta for proposta in propostas
                    if proposta.vaga_id == vaga.pk
                    and proposta.situacao in (
                        Atividade.SITUACAO_PENDENTE, Atividade.SITUACAO_APROVADA,
                    )
                ),
                None,
            ),
        })

    return {
        "kpis": kpis,
        "por_status": por_status,
        "por_espaco": sorted(
            por_espaco.values(), key=lambda bloco: sem_acento(bloco["espaco"].nome)
        ),
        "vagas_livres": livres,
        "propostas": propostas,
        "total_propostas": total,
        "total_vagas": total_vagas,
        "chamada": chamada_de(evento),
        "aberta": esta_aberta(evento),
        "situacao": situacao(evento),
    }


def eventos_do_organizador(usuario):
    """Eventos que este usuário gerencia (os mesmos do painel do organizador)."""
    from .models import Evento

    if usuario.is_superuser:
        return Evento.objects.all()
    return Evento.objects.filter(organizador=usuario)
