from django.urls import path

from . import views

app_name = "blog"

urlpatterns = [
    # Blog de um evento (índice público) e criação de post.
    path("evento/<int:evento_id>/", views.indice, name="indice"),
    path("evento/<int:evento_id>/novo/", views.criar, name="criar"),

    # Post individual e ações sobre ele.
    path("post/<int:post_id>/", views.post_detalhe, name="post"),
    path("post/<int:post_id>/editar/", views.editar, name="editar"),
    path("post/<int:post_id>/excluir/", views.excluir, name="excluir"),
    path("post/<int:post_id>/moderar/", views.moderar, name="moderar"),

    # Porta única das imagens (o storage aponta para /blog/privado/).
    path("privado/<path:path>", views.arquivo_privado, name="arquivo_privado"),
]
