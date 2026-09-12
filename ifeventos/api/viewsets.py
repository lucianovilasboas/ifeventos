from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from eventos.crachas import (
    atividade_aceita_presenca_agora,
    confirmar_por_token_atividade,
    crachas_do_usuario,
    gerar_token_atividade,
    janela_de_presenca,
    montar_cracha,
    pessoa_por_token_ou_codigo,
    png_qr,
    pode_exibir_qr_atividade,
    pode_gerenciar_evento,
    qr_como_data_url,
    registrar_presenca,
    url_presenca_atividade,
    verificar_token,
)
from eventos.models import Atividade, Certificado, Evento, Inscricao, Presenca, TipoAtividade

from .permissions import IsDonoEvento, IsDonoInscricao, IsDonoOuOrganizador, IsOrganizador
from .serializers import (
    AtividadeSerializer,
    AtividadeWriteSerializer,
    CertificadoSerializer,
    CrachaSerializer,
    EventoSerializer,
    EventoWriteSerializer,
    InscricaoCreateSerializer,
    InscricaoSerializer,
    PresencaCreateSerializer,
    PresencaSerializer,
    QrAtividadeSerializer,
    TipoAtividadeSerializer,
    TipoAtividadeWriteSerializer,
    VerificacaoSerializer,
)


class EventoViewSet(viewsets.ModelViewSet):
    """Catálogo público de eventos (leitura) + CRUD para organizadores."""

    # Leitura: qualquer um. Escrita: só is_organizador (D1).
    queryset = Evento.objects.all().order_by("-data_inicio")
    search_fields = ["title", "description", "local"]
    permission_classes = [AllowAny, IsOrganizador]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return EventoWriteSerializer
        return EventoSerializer

    def perform_create(self, serializer):
        serializer.save(organizador=self.request.user)

    def get_permissions(self):
        # Leitura: qualquer um. Escrita: exigir organizador e (no objeto) dono/superuser.
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        if self.action == "create":
            return [IsOrganizador()]
        return [IsOrganizador(), IsDonoEvento()]

    def get_object(self):
        obj = super().get_object()
        # Edição/exclusão exige dono do evento ou superuser.
        if self.action in ("update", "partial_update", "destroy"):
            self.check_object_permissions(self.request, obj)
        return obj


class AtividadeViewSet(viewsets.ModelViewSet):
    """Catálogo público de atividades + CRUD para organizadores."""

    queryset = Atividade.objects.select_related("tipo", "evento").prefetch_related("palestrantes").order_by("data_hora_inicio")
    search_fields = ["titulo", "descricao"]
    permission_classes = [AllowAny, IsOrganizador]

    @extend_schema(responses=QrAtividadeSerializer)
    @action(detail=True, methods=["get"], url_path="qrcode", url_name="qrcode")
    def qrcode(self, request, pk=None):
        """QR de presença da atividade — o código que a organização exibe na tela.

        Quem pode pedir: quem organiza o evento ou quem palestra nesta atividade
        (os dois estão na sala no momento). O código é assinado e vale por poucos
        minutos, e a tela renova de tempos em tempos — é isso que faz uma foto
        compartilhada do QR deixar de funcionar.
        """
        atividade = self.get_object()
        if not pode_exibir_qr_atividade(request.user, atividade):
            return Response(
                {"detail": "Você não organiza este evento nem palestra nesta atividade."},
                status=status.HTTP_403_FORBIDDEN,
            )

        url = url_presenca_atividade(gerar_token_atividade(atividade.id))
        abre_em, fecha_em = janela_de_presenca(atividade)
        aceita, motivo = atividade_aceita_presenca_agora(atividade)
        return Response({
            "atividade_id": atividade.id,
            "atividade": atividade.titulo,
            "url": url,
            "png": qr_como_data_url(url, caixa=10, borda=2),
            "validade_segundos": getattr(settings, "PRESENCA_QR_VALIDADE_SEGUNDOS", 300),
            "renovar_em_segundos": getattr(settings, "PRESENCA_QR_INTERVALO_RENOVACAO", 120),
            "janela": {
                "abre_em": abre_em,
                "fecha_em": fecha_em,
                "aberta": aceita,
                "motivo": motivo,
            },
        })

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return AtividadeWriteSerializer
        return AtividadeSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        if self.action == "create":
            return [IsOrganizador()]
        return [IsOrganizador(), IsDonoEvento()]

    def get_object(self):
        obj = super().get_object()
        if self.action in ("update", "partial_update", "destroy"):
            self.check_object_permissions(self.request, obj)
        return obj


class TipoAtividadeViewSet(viewsets.ModelViewSet):
    """Tipos de atividade: leitura pública, escrita para organizadores."""

    queryset = TipoAtividade.objects.all().order_by("nome")
    permission_classes = [AllowAny, IsOrganizador]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return TipoAtividadeWriteSerializer
        return TipoAtividadeSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsOrganizador()]


class MinhasInscricoesViewSet(viewsets.ModelViewSet):
    """Inscrições do usuário autenticado.

    - GET: lista as próprias (organizador vê todas).
    - POST: self-inscrição em uma atividade ({'atividade': id}), com as
      mesmas regras de negócio do site (vagas, duplicidade, conflito).
    - DELETE: cancela a própria inscrição.
    """

    serializer_class = InscricaoSerializer
    permission_classes = [IsAuthenticated, IsDonoOuOrganizador]

    def get_permissions(self):
        # DELETE (cancelar) é somente a própria inscrição; demais exigem
        # autenticação + permissão de objeto (IsDonoOuOrganizador na leitura).
        if self.action == "destroy":
            return [IsAuthenticated(), IsDonoInscricao()]
        return [IsAuthenticated(), IsDonoOuOrganizador()]

    def get_serializer_class(self):
        if self.action == "create":
            return InscricaoCreateSerializer
        return InscricaoSerializer

    def get_queryset(self):
        qs = Inscricao.objects.select_related("participante", "atividade__evento", "atividade__tipo").prefetch_related("atividade__palestrantes")
        user = self.request.user
        if getattr(user, "is_organizador", False):
            return qs.all()
        return qs.filter(participante=user)

    def perform_create(self, serializer):
        serializer.save(participante=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Cancela a própria inscrição e, junto, a presença naquela atividade.

        A regra vive em `eventos.inscricoes` — o mesmo lugar que a tela do
        participante usa. É lá que se decide recusar quando já existe
        certificado emitido, para não deixar certificado sem comprovação.
        """
        from eventos.inscricoes import InscricaoBloqueada, cancelar_inscricao

        inscricao = self.get_object()
        try:
            cancelar_inscricao(inscricao, por=request.user)
        except InscricaoBloqueada as bloqueio:
            return Response(
                {"detail": bloqueio.messages[0]}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get_object(self):
        obj = super().get_object()
        self.check_object_permissions(self.request, obj)
        return obj


class MeusCertificadosViewSet(viewsets.ReadOnlyModelViewSet):
    """Certificados do usuário autenticado (somente leitura, filtro por usuário)."""

    serializer_class = CertificadoSerializer
    permission_classes = [IsAuthenticated, IsDonoOuOrganizador]

    def get_queryset(self):
        qs = Certificado.objects.select_related("participante", "atividade", "evento")
        user = self.request.user
        if getattr(user, "is_organizador", False):
            return qs.all()
        return qs.filter(participante=user)

    def get_object(self):
        obj = super().get_object()
        self.check_object_permissions(self.request, obj)
        return obj

class MeusCrachasViewSet(viewsets.GenericViewSet):
    """Crachás do usuário autenticado — um por evento em que ele tem papel.

    Não há POST nem DELETE: o crachá é derivado de evento + pessoa + papel, não
    é registro no banco. O que cria ou tira um crachá é a pessoa ganhar ou
    perder o papel no evento (organizar, palestrar ou se inscrever).
    """

    permission_classes = [IsAuthenticated]
    serializer_class = CrachaSerializer

    @extend_schema(responses=CrachaSerializer(many=True))
    def list(self, request):
        dados = []
        for cracha in crachas_do_usuario(request.user):
            dados.append({
                "evento_id": cracha["evento"].id,
                "evento": cracha["evento"].title,
                "periodo": cracha["periodo"],
                "local": cracha["evento"].local,
                "papel": cracha["papel"],
                "papel_rotulo": cracha["papel_rotulo"],
                "nome": cracha["nome"],
                "codigo": cracha["codigo"],
                "token": cracha["token"],
                "url": cracha["url"],
                "qr_png": request.build_absolute_uri(
                    reverse("cracha-qr-png", kwargs={"evento_id": cracha["evento"].id})
                ),
            })
        return Response(self.get_serializer(dados, many=True).data)

class VerificacaoView(APIView):
    """Verifica um token de crachá ou de certificado. Endpoint PÚBLICO.

    É público de propósito: quem confere pode estar deslogado, na porta da
    atividade, e um app scanner não deve precisar de login para checar um
    crachá. Devolve só o necessário para a conferência — nome, papel e evento —
    e nenhum dado pessoal (CPF, e-mail e telefone não saem aqui).
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses=VerificacaoSerializer)
    def get(self, request, token):
        resultado = verificar_token(token)
        if not resultado["valido"]:
            return Response(
                {"valido": False, "erro": resultado["erro"]},
                status=resultado["status"],
            )

        evento = resultado.get("evento")
        atividade = resultado.get("atividade")
        return Response({
            "valido": True,
            "tipo": resultado["tipo"],
            "nome": resultado["nome"],
            "papel": resultado["papel"],
            "papel_rotulo": resultado["papel_rotulo"],
            "evento_id": evento.id if evento else None,
            "evento": evento.title if evento else None,
            "periodo": resultado.get("periodo", ""),
            "atividade_id": atividade.id if atividade else None,
            "atividade": atividade.titulo if atividade else None,
        })


class PresencaViewSet(viewsets.ModelViewSet):
    """Presenças por atividade: registrar o check-in, listar e desfazer.

    Quem opera é quem organiza o evento (staff, superusuário, quem tem a flag de
    organizador ou o organizador cadastrado no evento) — a MESMA regra da tela e
    da página pública, em `pode_gerenciar_evento`. Quem não organiza não vê a
    lista: o filtro do queryset devolve apenas as presenças dos eventos da
    pessoa.
    """

    serializer_class = PresencaSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        qs = Presenca.objects.select_related(
            "participante", "atividade", "atividade__evento", "registrada_por"
        )

        parametros = self.request.query_params
        if parametros.get("atividade"):
            qs = qs.filter(atividade_id=parametros["atividade"])
        if parametros.get("evento"):
            qs = qs.filter(atividade__evento_id=parametros["evento"])
        if parametros.get("participante"):
            qs = qs.filter(participante_id=parametros["participante"])

        usuario = self.request.user
        if usuario.is_staff or usuario.is_superuser or getattr(usuario, "is_organizador", False):
            return qs
        # Sem as permissões amplas, só as presenças dos eventos que organiza.
        return qs.filter(atividade__evento__organizador=usuario)

    @extend_schema(request=PresencaCreateSerializer, responses=PresencaSerializer)
    def create(self, request, *args, **kwargs):
        entrada = PresencaCreateSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados_entrada = entrada.validated_data

        # -- Forma 1: a própria pessoa confirma, com o QR da atividade ---------
        # Aqui a permissão é outra: não é a organização marcando presença de
        # alguém, é a pessoa confirmando a própria. Quem ela é vem da sessão.
        if dados_entrada.get("token_atividade"):
            atividade, presenca, criada, erro = confirmar_por_token_atividade(
                dados_entrada["token_atividade"], request.user
            )
            if presenca is None:
                return Response(
                    {"detail": erro, "atividade_id": atividade.id if atividade else None},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            dados = PresencaSerializer(presenca).data
            dados["criada"] = criada
            return Response(dados, status=status.HTTP_201_CREATED if criada else status.HTTP_200_OK)

        # -- Forma 2: a organização confirma ----------------------------------
        atividade = dados_entrada["atividade"]

        if not pode_gerenciar_evento(request.user, atividade.evento):
            return Response(
                {"detail": "Você não organiza o evento desta atividade."},
                status=status.HTTP_403_FORBIDDEN,
            )

        pessoa, _papel, _evento = pessoa_por_token_ou_codigo(
            token=dados_entrada.get("token"),
            codigo=dados_entrada.get("codigo"),
            evento=atividade.evento,
        )
        if pessoa is None:
            pessoa = dados_entrada.get("participante")

        if pessoa is None:
            return Response(
                {
                    "detail": "Não identifiquei a pessoa: o QR pode ser de outro evento, "
                              "ou o código digitado não confere."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if dados_entrada.get("origem"):
            origem = dados_entrada["origem"]
        elif dados_entrada.get("codigo"):
            origem = "codigo"
        elif dados_entrada.get("participante") and not dados_entrada.get("token"):
            origem = "manual"
        else:
            origem = "qr"

        presenca, criada, motivo = registrar_presenca(
            atividade, pessoa, registrada_por=request.user, origem=origem
        )
        if presenca is None:
            # O motivo já explica qual das duas razões barrou: falta de vínculo
            # com o evento ou estar fora da janela de confirmação da atividade.
            return Response({"detail": motivo}, status=status.HTTP_400_BAD_REQUEST)

        dados = PresencaSerializer(presenca).data
        dados["criada"] = criada
        return Response(dados, status=status.HTTP_201_CREATED if criada else status.HTTP_200_OK)

    def perform_destroy(self, instance):
        """Desfazer presença deixa rastro de quem desfez.

        O `destroy()` padrão do DRF chama `instance.delete()`, que cumpre a
        parte de estado (desmarca a inscrição) mas NÃO registra auditoria. Como
        esta é a rota usada pelo ✕ da tela do QR e pelo "desfazer" do check-in,
        é aqui que o cancelamento passa a ser auditado.
        """
        instance.cancelar(
            por=self.request.user,
            motivo="Desfazer presença (check-in/QR)",
        )

    def destroy(self, request, *args, **kwargs):
        presenca = self.get_object()
        if not pode_gerenciar_evento(request.user, presenca.atividade.evento):
            return Response(
                {"detail": "Você não organiza o evento desta atividade."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().destroy(request, *args, **kwargs)


class CrachasEventoPDFView(APIView):
    """PDF com os crachás de todas as pessoas com papel no evento (10 x 7 cm).

    Uma página por pessoa: serve para imprimir em lote e entregar no
    credenciamento.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={(200, "application/pdf"): OpenApiResponse(description="PDF dos crachás")})
    def get(self, request, evento_id):
        evento = get_object_or_404(Evento, id=evento_id)
        if not pode_gerenciar_evento(request.user, evento):
            return Response(
                {"detail": "Você não organiza este evento."},
                status=status.HTTP_403_FORBIDDEN,
            )

        from eventos.crachas import gerar_pdf_crachas_evento

        nome_arquivo, conteudo = gerar_pdf_crachas_evento(evento)
        resposta = HttpResponse(conteudo.read(), content_type="application/pdf")
        resposta["Content-Disposition"] = f'inline; filename="{nome_arquivo}"'
        return resposta


# ---------------------------------------------------------------------------
# Imagens dos QR em rota explícita
#
# Estas duas não são ações de viewset de propósito: o roteador do DRF gera, para
# cada ação, um padrão de sufixo de formato (`/qrcode.<formato>/`) que casa antes
# do caminho literal — pedir `/qrcode.png/` acaba virando "formato=png", que não
# existe, e a resposta é 404. Em rota explícita o caminho é literal e não depende
# da ordem em que as ações foram declaradas.
# ---------------------------------------------------------------------------


class QrAtividadePngView(APIView):
    """PNG do QR de presença da atividade (código novo a cada pedido)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={(200, "image/png"): OpenApiResponse(description="PNG do QR da atividade")})
    def get(self, request, atividade_id):
        atividade = get_object_or_404(Atividade, id=atividade_id)
        if not pode_exibir_qr_atividade(request.user, atividade):
            return Response(
                {"detail": "Você não organiza este evento nem palestra nesta atividade."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return HttpResponse(
            png_qr(url_presenca_atividade(gerar_token_atividade(atividade.id)), caixa=10, borda=2),
            content_type="image/png",
        )


class QrCrachaPngView(APIView):
    """PNG do QR do crachá do usuário logado em um evento."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={(200, "image/png"): OpenApiResponse(description="PNG do QR do crachá")})
    def get(self, request, evento_id):
        evento = get_object_or_404(Evento, id=evento_id)
        cracha = montar_cracha(request.user, evento)
        if cracha is None:
            return Response(
                {"detail": "Você não tem crachá neste evento."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return HttpResponse(png_qr(cracha["url"], caixa=10, borda=2), content_type="image/png")
