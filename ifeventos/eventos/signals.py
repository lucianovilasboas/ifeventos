from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from allauth.account.signals import user_logged_in, user_signed_up
from allauth.socialaccount.signals import social_account_added, social_account_updated
from .models import Inscricao 
from .models import Atividade
from .models import Presenca
from .services import notify_socketio


# Atualiza o número de inscrições sempre que uma nova inscrição é criada ou removida
@receiver(post_save, sender=Inscricao)
@receiver(post_delete, sender=Inscricao)
def atualizar_inscricoes(sender, instance, **kwargs):
    atividade = instance.atividade  # Obtém a atividade associada à inscrição
    atividade.inscricoes = Inscricao.objects.filter(atividade=atividade).count()

    atividade.save()  

    notify_socketio("update_inscricao", {
        "atividade_id": atividade.id,
        "n_inscricoes": atividade.inscricoes,
        "acao": "inscricao",
    })





def _iso(valor):
    """devolve a data em ISO, aceitando datetime/date ou string já pronta.

    O campo pode chegar aqui como string quando o objeto foi criado sem passar
    pelo formulário/serializer (o Django converte só na hora de gravar, e o
    atributo do instance continua str) — chamar .isoformat() direto estourava
    AttributeError.
    """
    if valor is None:
        return None
    isoformat = getattr(valor, "isoformat", None)
    return isoformat() if callable(isoformat) else str(valor)


@receiver(post_save, sender=Atividade)
def atividade_salva(sender, instance, created, **kwargs):
    data = {
        "titulo": instance.titulo,
        "local": instance.local,
        "evento": instance.evento.title if instance.evento_id else None,
        # `tipo` é opcional no model: sem o guarda, criar atividade sem tipo
        # estourava AttributeError ('NoneType' has no attribute 'nome') -> 500.
        "tipo": instance.tipo.nome if instance.tipo else None,
        "id": instance.id,
        "n_vagas": instance.n_vagas,
        "n_inscricoes": instance.n_inscricoes,
        "data_hora_inicio": _iso(instance.data_hora_inicio),
        "data_hora_fim": _iso(instance.data_hora_fim),
        # A lista aberta monta a linha com isto: a data já vai formatada (o
        # navegador não repetiria a conversão de fuso) e a flag decide se o
        # botão de certificado aparece naquela atividade.
        "quando": instance.quando_legivel,
        "emite_certificado": instance.emite_certificado,
        # Para o card criado em tempo real mostrar a miniatura da atividade.
        "imagem_url": instance.imagem.url if instance.imagem else None,
        "acao": "atividade",
    }

    
    tipo = "new_activity"  if created else "update_atividate"

    print(f"Tipo: {tipo}")
    print(f"Data: {data}")

    notify_socketio(tipo, data)



@receiver(post_delete, sender=Atividade)
def atividade_deletada(sender, instance, **kwargs):
    data = {
        "titulo": instance.titulo,
        "id": instance.id,
        "acao": "atividade",
    }

    notify_socketio("delete_activity", data)


@receiver(post_delete, sender=Inscricao)
def remover_presenca_da_inscricao(sender, instance, **kwargs):
    """Rede de segurança: inscrição removida não deixa presença para trás.

    O caminho normal é `eventos.inscricoes.cancelar_inscricao`, que cancela a
    presença COM auditoria e é o único que consegue recusar quando já existe
    certificado emitido. Este receiver cobre o que não passa por lá — o admin,
    um `queryset.delete()` em lote e qualquer código futuro. Quando o serviço já
    cancelou, aqui não encontra nada e não faz nada.

    Aqui a presença é apagada SEM auditoria, de propósito. Excluir uma
    atividade, um evento ou uma pessoa passa por este receiver em cascata:
    gravar auditoria nesse instante apontaria para o registro que está sendo
    apagado na MESMA transação — a chave estrangeira quebra e a exclusão morre.
    Auditoria é para ação de gente, e essas já são registradas em
    `cancelar_inscricao` e em `Presenca.cancelar`.
    """
    Presenca.objects.filter(
        participante=instance.participante, atividade=instance.atividade
    ).delete()


@receiver(post_delete, sender=Presenca)
def presenca_removida(sender, instance, **kwargs):
    """Avisa as telas abertas (QR da atividade, check-in) que a presença saiu.

    Sem isto a lista da outra tela só se corrige na próxima atualização
    periódica (10 s) — e quem está na porta vê um nome que já não vale.
    """
    data = {
        "presenca_id": instance.id,
        "atividade_id": instance.atividade_id,
        "acao": "presenca",
    }
    notify_socketio("presenca_cancelada", data)


# Pré-carga da planilha: completa o perfil no PRIMEIRO ACESSO.
#
# `user_signed_up` cobre a criação da conta (cadastro local e auto-cadastro pelo
# Google). `user_logged_in` cobre os casos em que a conta JÁ existia antes de a
# planilha existir: o auto-connect do Google numa conta pré-cadastrada e as
# contas criadas por importação em lote — nelas o `user_signed_up` nunca dispara.
# A guarda de `completar_do_roster` (linha `usado_em`) garante que roda uma vez
# só e não sobrescreve o que a pessoa editar depois. Nunca levanta exceção.
@receiver(user_signed_up)
@receiver(user_logged_in)
def completar_perfil_pelo_roster(request, user, **kwargs):
    from . import roster

    roster.completar_do_roster(user)


# Enriquecimento do perfil pelo login social (nome/avatar do Google).
#
# `social_account_added` cobre o auto-connect de uma conta que JÁ existia (caso
# em que o `save_user` do adapter não roda); `social_account_updated` cobre os
# logins seguintes. Só age quando ainda falta algo no perfil.
@receiver(social_account_added)
@receiver(social_account_updated)
def enriquecer_perfil_social(request, sociallogin, **kwargs):
    from . import social

    conta = getattr(sociallogin, "account", None)
    if getattr(conta, "provider", "") != "google":
        return
    user = getattr(sociallogin, "user", None)
    if user is not None:
        social.enriquecer_do_google(user, sociallogin)



# ---------------------------------------------------------------------------
# Trilha de auditoria
# ---------------------------------------------------------------------------
# Camada automática (models): registra criar/editar/excluir das entidades
# editoriais. As ações de negócio (emissão, propostas, login, config…) e a
# configuração de certificado são registradas explicitamente nas views para
# não poluir com criações implícitas (ex.: `_get_config` num GET).
from django.db.models.signals import pre_save
from django.contrib.auth.signals import (
    user_logged_in as django_user_logged_in,
    user_logged_out as django_user_logged_out,
)

from .models import (
    ChamadaProposicoes,
    Espaco,
    Evento,
    RegistroAuditoria,
    Vaga,
)

# Campos relevantes por model: o "editar" só registra se algum mudou, e guarda
# o antes/depois no `detalhes`.
_CAMPOS_AUDITADOS = {
    "evento": [
        "title", "description", "local", "data_inicio", "data_fim",
        "categoria", "carga_horaria", "percentual_certificado", "modelo_cracha",
    ],
    "atividade": [
        "titulo", "descricao", "local", "data_hora_inicio", "data_hora_fim",
        "n_vagas", "emite_certificado", "tipo_id", "situacao", "motivo_rejeicao",
    ],
    "espaco": ["nome", "capacidade"],
    "vaga": ["espaco_id", "inicio", "fim", "capacidade"],
    "chamadaproposicoes": ["titulo", "descricao", "inicio", "fim", "aberta"],
}
# Movimentação em massa: interessa criar/excluir, não cada update.
_SO_CRIAR = {"inscricao", "presenca"}


def _valor_texto(valor, limite=300):
    if valor is None:
        return ""
    return str(valor)[:limite]


@receiver(pre_save)
def auditoria_pre_save(sender, instance, **kwargs):
    campos = _CAMPOS_AUDITADOS.get(sender.__name__.lower())
    if not campos or not instance.pk:
        return
    try:
        antigo = sender.objects.filter(pk=instance.pk).only(*campos).first()
    except Exception:
        antigo = None
    if antigo is not None:
        instance._auditoria_antes = {
            c: _valor_texto(getattr(antigo, c, None)) for c in campos
        }


@receiver(post_save)
def auditoria_post_save(sender, instance, created, **kwargs):
    from . import auditoria

    nome = sender.__name__.lower()
    audita_edicao = nome in _CAMPOS_AUDITADOS
    if not (audita_edicao or nome in _SO_CRIAR):
        return
    if created:
        auditoria.registrar(
            acao=RegistroAuditoria.ACAO_CRIAR,
            objeto=instance,
            resumo=f"Criou {sender.__name__}",
        )
        return
    if not audita_edicao:
        return
    antes = getattr(instance, "_auditoria_antes", None)
    if not antes:
        return
    alteracoes = {}
    for campo in _CAMPOS_AUDITADOS[nome]:
        depois = _valor_texto(getattr(instance, campo, None))
        if antes.get(campo, "") != depois:
            alteracoes[campo] = {"antes": antes.get(campo, ""), "depois": depois}
    if not alteracoes:
        return
    auditoria.registrar(
        acao=RegistroAuditoria.ACAO_EDITAR,
        objeto=instance,
        resumo=f"Editou {sender.__name__}",
        detalhes={"alteracoes": alteracoes},
    )


@receiver(post_delete)
def auditoria_post_delete(sender, instance, **kwargs):
    from . import auditoria

    nome = sender.__name__.lower()
    if nome not in _CAMPOS_AUDITADOS:
        return
    # No delete não usamos FK para o evento nem para o objeto: podem estar indo
    # embora em cascata (apagar um evento apaga as atividades/vagas junto).
    auditoria.registrar(
        acao=RegistroAuditoria.ACAO_EXCLUIR,
        entidade=sender.__name__,
        objeto_id=str(getattr(instance, "pk", "") or ""),
        objeto_repr=_valor_texto(instance, 255),
        evento=None,
        resumo=f"Excluiu {sender.__name__}",
    )


@receiver(django_user_logged_in)
def auditoria_login(request, user, **kwargs):
    from . import auditoria

    auditoria.registrar(
        acao=RegistroAuditoria.ACAO_LOGIN,
        entidade="Participante",
        objeto_id=str(getattr(user, "pk", "") or ""),
        objeto_repr=_valor_texto(user, 255),
        usuario=user,
        request=request,
        resumo="Entrou no sistema",
    )


@receiver(django_user_logged_out)
def auditoria_logout(request, user, **kwargs):
    from . import auditoria

    if user is None:
        return
    auditoria.registrar(
        acao=RegistroAuditoria.ACAO_LOGOUT,
        entidade="Participante",
        objeto_id=str(getattr(user, "pk", "") or ""),
        objeto_repr=_valor_texto(user, 255),
        usuario=user,
        request=request,
        resumo="Saiu do sistema",
    )
