"""Views do blog do evento.

Regras de acesso (espelham o resto do sistema, sem inventar permissão nova):

- leitura: pública para posts PUBLICADOS; autor e moderadores veem os demais;
- escrita de participante: quem tem inscrição OU presença em atividade do evento,
  e o post entra como PENDENTE (curadoria do organizador);
- moderador (dono/co-organizador/staff): publica direto, aprova, oculta e fixa;
- edição de um post já publicado por participante volta para PENDENTE.
"""

import mimetypes

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from eventos import auditoria
from eventos.crachas import pode_gerenciar_evento
from eventos.models import Evento, Inscricao, Presenca, RegistroAuditoria

from .forms import MAX_FOTOS_POR_POST, PostForm, validar_imagem
from .models import FotoPost, PostEvento, storage_blog

LOGIN_URL = "/accounts/login/"


def participou_do_evento(usuario, evento):
    """A pessoa tem inscrição ou presença em alguma atividade do evento?"""
    if Inscricao.objects.filter(
        participante=usuario, atividade__evento=evento
    ).exists():
        return True
    return Presenca.objects.filter(
        participante=usuario, atividade__evento=evento
    ).exists()


def pode_publicar_no_evento(usuario, evento):
    if not usuario or not getattr(usuario, "is_authenticated", False):
        return False
    if pode_gerenciar_evento(usuario, evento):
        return True
    return participou_do_evento(usuario, evento)


def _coletar_fotos(request):
    """Valida os arquivos enviados: devolve (validos, erros)."""
    validos, erros = [], []
    for arquivo in request.FILES.getlist("fotos"):
        erro = validar_imagem(arquivo)
        if erro:
            erros.append(f"{arquivo.name}: {erro}")
        else:
            validos.append(arquivo)
    return validos, erros


def indice(request, evento_id):
    """Lista pública dos posts publicados; autor vê os seus não publicados."""
    evento = get_object_or_404(Evento, id=evento_id)
    posts = (
        evento.posts_blog.filter(situacao=PostEvento.SIT_PUBLICADO)
        .select_related("autor")
        .prefetch_related("fotos")
    )
    pagina = Paginator(posts, 9).get_page(request.GET.get("pagina"))

    meus = PostEvento.objects.none()
    if request.user.is_authenticated:
        meus = (
            evento.posts_blog.filter(autor=request.user)
            .exclude(situacao=PostEvento.SIT_PUBLICADO)
            .order_by("-criado_em")
        )

    return render(
        request,
        "blog/indice.html",
        {
            "evento": evento,
            "pagina": pagina,
            "meus": meus,
            "pode_publicar": pode_publicar_no_evento(request.user, evento),
        },
    )


def post_detalhe(request, post_id):
    post = get_object_or_404(
        PostEvento.objects.select_related("evento", "autor").prefetch_related("fotos"),
        id=post_id,
    )
    if not post.visivel_para(request.user):
        raise Http404("Post não encontrado.")

    eh_autor = request.user.is_authenticated and post.autor_id == request.user.id
    eh_moderador = pode_gerenciar_evento(request.user, post.evento)
    return render(
        request,
        "blog/post.html",
        {
            "post": post,
            "evento": post.evento,
            "eh_autor": eh_autor,
            "eh_moderador": eh_moderador,
            "pode_editar": eh_autor or eh_moderador,
        },
    )


@login_required(login_url=LOGIN_URL)
def criar(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    if not pode_publicar_no_evento(request.user, evento):
        raise PermissionDenied(
            "Só quem participou do evento (ou a organização) pode escrever no blog."
        )
    eh_moderador = pode_gerenciar_evento(request.user, evento)
    form = PostForm(request.POST or None, request.FILES or None)

    if request.method == "POST":
        fotos, erros = _coletar_fotos(request)
        if len(fotos) > MAX_FOTOS_POR_POST:
            erros.append(f"Envie no máximo {MAX_FOTOS_POR_POST} fotos por post.")
        if form.is_valid() and not erros:
            post = form.save(commit=False)
            post.evento = evento
            post.autor = request.user
            post.autor_nome = request.user.get_full_name() or request.user.username
            acao = request.POST.get("acao", "")
            if eh_moderador and acao == "publicar":
                post.situacao = PostEvento.SIT_PUBLICADO
            elif eh_moderador and acao == "rascunho":
                post.situacao = PostEvento.SIT_RASCUNHO
            else:
                post.situacao = PostEvento.SIT_PENDENTE
            post.save()
            for i, arquivo in enumerate(fotos):
                FotoPost.objects.create(post=post, imagem=arquivo, ordem=i)
            auditoria.registrar(
                acao=RegistroAuditoria.ACAO_CRIAR,
                objeto=post,
                evento=evento,
                usuario=request.user,
                resumo=f"Criou o post “{post.titulo}” no blog do evento",
            )
            if post.situacao == PostEvento.SIT_PENDENTE:
                messages.success(
                    request,
                    "Sua história foi enviada e aguarda a aprovação do organizador.",
                )
            else:
                messages.success(request, "Post salvo.")
            return redirect("blog:post", post.id)
        for erro in erros:
            messages.error(request, erro)

    return render(
        request,
        "blog/form.html",
        {"evento": evento, "form": form, "post": None,
         "eh_moderador": eh_moderador, "fotos": []},
    )


@login_required(login_url=LOGIN_URL)
def editar(request, post_id):
    post = get_object_or_404(PostEvento, id=post_id)
    eh_autor = post.autor_id == request.user.id
    eh_moderador = pode_gerenciar_evento(request.user, post.evento)
    if not (eh_autor or eh_moderador):
        raise PermissionDenied("Você só pode editar os seus próprios posts.")

    form = PostForm(request.POST or None, request.FILES or None, instance=post)

    if request.method == "POST":
        fotos, erros = _coletar_fotos(request)
        remover = request.POST.getlist("remover_foto")
        restantes = post.fotos.exclude(id__in=remover).count()
        if restantes + len(fotos) > MAX_FOTOS_POR_POST:
            erros.append(f"O post pode ter no máximo {MAX_FOTOS_POR_POST} fotos.")
        if form.is_valid() and not erros:
            post = form.save(commit=False)
            for foto in post.fotos.filter(id__in=remover):
                foto.delete()
            acao = request.POST.get("acao", "")
            if eh_moderador and acao == "publicar":
                post.situacao = PostEvento.SIT_PUBLICADO
            elif eh_moderador and acao == "rascunho":
                post.situacao = PostEvento.SIT_RASCUNHO
            elif eh_autor and not eh_moderador and post.situacao == PostEvento.SIT_PUBLICADO:
                # Editar um post já publicado exige nova curadoria.
                post.situacao = PostEvento.SIT_PENDENTE
            post.save()
            base = post.fotos.count()
            for i, arquivo in enumerate(fotos):
                FotoPost.objects.create(post=post, imagem=arquivo, ordem=base + i)
            auditoria.registrar(
                acao=RegistroAuditoria.ACAO_EDITAR,
                objeto=post,
                evento=post.evento,
                usuario=request.user,
                resumo=f"Editou o post “{post.titulo}” no blog do evento",
            )
            if post.situacao == PostEvento.SIT_PENDENTE:
                messages.success(request, "Alterações salvas e reenviadas para aprovação.")
            else:
                messages.success(request, "Post atualizado.")
            return redirect("blog:post", post.id)
        for erro in erros:
            messages.error(request, erro)

    return render(
        request,
        "blog/form.html",
        {"evento": post.evento, "form": form, "post": post,
         "eh_moderador": eh_moderador, "fotos": post.fotos.all()},
    )


@login_required(login_url=LOGIN_URL)
@require_POST
def excluir(request, post_id):
    post = get_object_or_404(PostEvento, id=post_id)
    eh_autor = post.autor_id == request.user.id
    if not (eh_autor or pode_gerenciar_evento(request.user, post.evento)):
        raise PermissionDenied("Você só pode excluir os seus próprios posts.")
    evento = post.evento
    auditoria.registrar(
        acao=RegistroAuditoria.ACAO_EXCLUIR,
        objeto=post,
        evento=evento,
        usuario=request.user,
        resumo=f"Excluiu o post “{post.titulo}” do blog do evento",
    )
    post.delete()
    messages.success(request, "Post excluído.")
    return redirect("blog:indice", evento.id)


@login_required(login_url=LOGIN_URL)
@require_POST
def moderar(request, post_id):
    """Aprova, oculta, devolve ao rascunho ou (des)fixa um post."""
    post = get_object_or_404(PostEvento, id=post_id)
    if not pode_gerenciar_evento(request.user, post.evento):
        raise PermissionDenied("Apenas a organização do evento pode moderar o blog.")

    acao = request.POST.get("acao", "")
    campos = {"atualizado_em": timezone.now()}
    resposta = None
    if acao == "aprovar":
        campos["situacao"] = PostEvento.SIT_PUBLICADO
        if not post.publicado_em:
            campos["publicado_em"] = timezone.now()
        resposta = "Post publicado."
    elif acao == "ocultar":
        campos["situacao"] = PostEvento.SIT_OCULTO
        resposta = "Post ocultado."
    elif acao == "despublicar":
        campos["situacao"] = PostEvento.SIT_RASCUNHO
        resposta = "Post devolvido ao rascunho."
    elif acao == "fixar":
        campos["fixado"] = True
        resposta = "Post fixado no topo."
    elif acao == "desafixar":
        campos["fixado"] = False
        resposta = "Post desafixado."
    else:
        raise Http404("Ação de moderação desconhecida.")

    # update() evita reexecutar o redimensionamento da capa a cada moderação.
    PostEvento.objects.filter(pk=post.pk).update(**campos)
    auditoria.registrar(
        acao=RegistroAuditoria.ACAO_EDITAR,
        objeto=post,
        evento=post.evento,
        usuario=request.user,
        resumo=f"Moderou o post “{post.titulo}” ({acao})",
        detalhes={"acao_moderacao": acao},
    )
    messages.success(request, resposta)
    return redirect("blog:post", post.id)


def arquivo_privado(request, path):
    """Libera uma imagem do blog só quando o post é visível para quem pede.

    As imagens ficam fora do MEDIA_ROOT; esta view é a única porta. Publicado é
    público; pendente/oculto só para o autor e os moderadores.
    """
    post = PostEvento.objects.filter(capa=path).select_related("evento").first()
    if post is None:
        foto = (
            FotoPost.objects.select_related("post__evento")
            .filter(imagem=path)
            .first()
        )
        if foto is None:
            raise Http404
        post = foto.post
    if not post.visivel_para(request.user):
        raise Http404

    try:
        arquivo = storage_blog().open(path, "rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404

    tipo, _ = mimetypes.guess_type(path)
    resposta = FileResponse(arquivo, content_type=tipo or "application/octet-stream")
    resposta["Cache-Control"] = (
        "public, max-age=3600" if post.publicado else "private, no-store"
    )
    return resposta
