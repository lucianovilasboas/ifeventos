from django.conf import settings
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, AllowAny, IsAuthenticated
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
    pode_checkin_apoio,
    pode_gerenciar_evento,
    qr_como_data_url,
    registrar_presenca,
    url_presenca_atividade,
    verificar_token,
)
from eventos import metadados as metadados_config
from eventos import propostas
from eventos.regras import atividades_publicas
from eventos.models import (
    Atividade,
    Certificado,
    ChamadaProposicoes,
    Espaco,
    Evento,
    Inscricao,
    Participante,
    Presenca,
    TipoAtividade,
    Vaga,
)
from eventos.propostas import PropostaBloqueada

from .permissions import (
    IsDonoEvento,
    IsDonoInscricao,
    IsDonoOuOrganizador,
    IsOrganizador,
    IsOrganizadorEstrito,
    PodeLerPresencas,
)
from .serializers import (
    AtividadeSerializer,
    AtividadeWriteSerializer,
    CertificadoSerializer,
    ChamadaProposicoesSerializer,
    ChamadaProposicoesWriteSerializer,
    DecisaoPropostaSerializer,
    CrachaSerializer,
    EspacoSerializer,
    EventoSerializer,
    EventoWriteSerializer,
    GradeVagasSerializer,
    ImportarMetadadosSerializer,
    InscricaoCreateSerializer,
    InscricaoSerializer,
    MeuPerfilSerializer,
    PalestranteSerializer,
    PalestranteWriteSerializer,
    PresencaCreateSerializer,
    PresencaSerializer,
    PropostaWriteSerializer,
    RejeicaoPropostaSerializer,
    QrAtividadeSerializer,
    TipoAtividadeSerializer,
    TipoAtividadeWriteSerializer,
    VagaResumoSerializer,
    VagaSerializer,
    VerificacaoSerializer,
)


class EventoViewSet(viewsets.ModelViewSet):
    """Catálogo público de eventos (leitura) + CRUD para organizadores."""

    # Leitura: qualquer um. Escrita: só is_organizador (D1).
    queryset = Evento.objects.all().order_by("-data_inicio")
    search_fields = ["title", "description", "local"]
    permission_classes = [AllowAny, IsOrganizador]

    def get_queryset(self):
        # `n_atividades` anotado evita um COUNT por evento nas listagens.
        return (
            Evento.objects.annotate(n_atividades=Count("atividades"))
            .order_by("-data_inicio")
        )

    # ------------------------------------------------------------------
    # Chamada de proposições de atividades (a regra vive em eventos.propostas)
    # ------------------------------------------------------------------
    @extend_schema(responses=ChamadaProposicoesSerializer)
    @action(detail=True, methods=["get", "put"], url_path="chamada", url_name="chamada")
    def chamada(self, request, pk=None):
        """Janela de proposições do evento.

        GET (autenticado): a janela e as vagas livres — é o que o formulário do
        proponente precisa. PUT (organizador dono): abre/atualiza/encerra.
        """
        evento = self.get_object()
        chamada = propostas.chamada_de(evento)

        if request.method == "GET":
            if chamada is None:
                return Response(
                    {"detail": "Este evento ainda não abriu chamada de propostas."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response(ChamadaProposicoesSerializer(chamada).data)

        entrada = ChamadaProposicoesWriteSerializer(
            instance=chamada, data=request.data, partial=True
        )
        entrada.is_valid(raise_exception=True)
        chamada = entrada.save(evento=evento)
        return Response(ChamadaProposicoesSerializer(chamada).data)

    @extend_schema(responses={200: OpenApiResponse(description="Indicadores da chamada")})
    @action(detail=True, methods=["get"], url_path="painel-chamada",
            url_name="painel-chamada")
    def painel_chamada(self, request, pk=None):
        """Indicadores da chamada (organizador): KPIs, ocupação e vagas livres.

        `eventos.propostas.resumo` é feito para template (devolve models), então
        aqui ele é achatado em JSON. Para as propostas em si, use
        `/propostas/?evento=<id>` — o painel só devolve os números.
        """
        evento = self.get_object()
        dados = propostas.resumo(evento)
        return Response({
            "kpis": dados["kpis"],
            "por_status": dados["por_status"],
            "total_propostas": dados["total_propostas"],
            "vagas_livres": VagaResumoSerializer(dados["vagas_livres"], many=True).data,
            "por_espaco": [
                {
                    "espaco": bloco["espaco"].nome,
                    "total": bloco["total"],
                    "livres": bloco["livres"],
                }
                for bloco in dados["por_espaco"]
            ],
        })

    @extend_schema(request=GradeVagasSerializer)
    @action(detail=True, methods=["post"], url_path="vagas/gerar",
            url_name="vagas-gerar")
    def vagas_gerar(self, request, pk=None):
        """Gera a grade em lote (dias × blocos × espaços), sem duplicar."""
        evento = self.get_object()
        entrada = GradeVagasSerializer(data=request.data, context={"evento": evento})
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        resultado = propostas.gerar_grade(
            evento,
            dias=dados["dias"],
            blocos=dados["blocos_limpos"],
            espacos=dados["espacos"],
            capacidade=dados.get("capacidade"),
        )
        return Response(resultado, status=status.HTTP_201_CREATED)

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
        if self.action == "chamada":
            # A janela e as vagas livres interessam ao proponente logado; abrir
            # e encerrar é do organizador dono (o padrão de escrita abaixo).
            if self.request.method in SAFE_METHODS:
                return [IsAuthenticated()]
            return [IsOrganizador(), IsDonoEvento()]
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

    def get_queryset(self):
        base = (
            Atividade.objects.select_related("tipo", "evento")
            .prefetch_related("palestrantes")
            .order_by("data_hora_inicio")
        )
        usuario = self.request.user
        gerencia = (
            usuario.is_staff
            or usuario.is_superuser
            or getattr(usuario, "is_organizador", False)
        )
        # Rascunho e proposta ainda não aprovada NÃO são catálogo público — é o
        # que a tela já faz (programação/landing/.ics/PDF filtram `publicada`).
        # Sem isto, a API devolvia rascunhos (e, agora, propostas) para qualquer
        # um. Quem gerencia continua vendo tudo.
        if self.action in ("list", "retrieve") and not gerencia:
            return atividades_publicas(base)
        return base

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
        if self.action == "qrcode":
            # O QR é leitura e a checagem fina (dono do evento OU palestrante) é
            # feita no corpo da action (`pode_exibir_qr_atividade`). Sem isto, o
            # palestrante — que tem o QR liberado na tela — esbarrava no
            # IsDonoEvento e recebia 403 da API.
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


class PalestranteViewSet(viewsets.ModelViewSet):
    """Palestrantes = Participante com `is_palestrante=True`.

    Dados pessoais (cpf, telefone, endereço): leitura E escrita exigem
    organizador (`IsOrganizadorEstrito`), inclusive a listagem — não é catálogo
    público. Sem DELETE de propósito: apagar a conta quebra atividades e
    inscrições; o papel se remove mexendo na pessoa, não por aqui.
    """

    queryset = Participante.objects.filter(is_palestrante=True).order_by(
        "first_name", "last_name"
    )
    search_fields = ["first_name", "last_name", "email"]
    permission_classes = [IsOrganizadorEstrito]
    http_method_names = ["get", "post", "put", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return PalestranteWriteSerializer
        return PalestranteSerializer

    def create(self, request, *args, **kwargs):
        """Cria o palestrante; se o e-mail já existir, atualiza e garante o papel.

        O POST repetido (reimportação, LLM reenviando) não deve virar 400: a
        conta existente é reaproveitada e recebe `is_palestrante=True`.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data
        metadados_novos = dados.pop("metadados", None)

        existente = Participante.objects.filter(email__iexact=dados["email"]).first()
        if existente:
            for campo, valor in dados.items():
                setattr(existente, campo, valor)
            existente.is_participante = True
            existente.is_palestrante = True
            existente.save()
            if metadados_novos is not None:
                metadados_config.salvar(existente, metadados_novos)
            return Response(
                PalestranteSerializer(existente).data, status=status.HTTP_200_OK
            )

        novo = Participante.objects.create_user(
            email=dados["email"],
            first_name=dados.get("first_name", ""),
            last_name=dados.get("last_name", ""),
            cpf=dados.get("cpf", ""),
            telefone=dados.get("telefone", ""),
            endereco=dados.get("endereco", ""),
            is_participante=True,
            is_palestrante=True,
        )
        # Palestrante não faz login: sem senha utilizável.
        novo.set_unusable_password()
        novo.save(update_fields=["password"])
        if metadados_novos is not None:
            metadados_config.salvar(novo, metadados_novos)
        # Pré-carga: se o e-mail do palestrante estiver na planilha, completa os
        # dados que faltam (os metadados do payload têm prioridade).
        from eventos import roster

        roster.completar_do_roster(novo)
        return Response(
            PalestranteSerializer(novo).data, status=status.HTTP_201_CREATED
        )

    def perform_update(self, serializer):
        # `metadados` não é campo do model: grava no JSON após salvar a pessoa.
        metadados_novos = serializer.validated_data.pop("metadados", None)
        instance = serializer.save()
        if metadados_novos is not None:
            metadados_config.salvar(instance, metadados_novos)


class MinhasInscricoesViewSet(viewsets.ModelViewSet):
    """Inscrições do usuário autenticado.

    - GET: lista as próprias (organizador vê todas).
    - POST: self-inscrição em uma atividade ({'atividade': id}), com as
      mesmas regras de negócio do site (vagas, duplicidade, conflito).
    - DELETE: cancela a própria inscrição.
    """

    serializer_class = InscricaoSerializer
    permission_classes = [IsAuthenticated, IsDonoOuOrganizador]
    # `queryset` base só para o drf-spectacular tipar o `{id}` do path (a
    # listagem real sai do get_queryset, filtrada por usuário).
    queryset = Inscricao.objects.none()

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
    queryset = Certificado.objects.none()  # idem: tipa o `{id}` na doc

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
    queryset = Presenca.objects.none()  # idem: tipa o `{id}` na doc

    def get_permissions(self):
        # Ler a lista é do organizador do evento/equipe de apoio (API.md:142);
        # registrar (create) segue aberto a quem tem papel no evento.
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated(), PodeLerPresencas()]
        return [IsAuthenticated()]

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
        if usuario.is_staff or usuario.is_superuser:
            return qs
        # Escopo por evento (2.3.0): só as presenças dos eventos que a pessoa
        # organiza/co-organiza ou onde é da equipe de apoio. A flag sozinha não
        # abre evento alheio.
        return qs.filter(
            Q(atividade__evento__organizador=usuario)
            | Q(atividade__evento__organizadores=usuario)
            | Q(atividade__evento__equipe=usuario)
        ).distinct()

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
            dados = PresencaSerializer(
                presenca, context=self.get_serializer_context()
            ).data
            dados["criada"] = criada
            return Response(dados, status=status.HTTP_201_CREATED if criada else status.HTTP_200_OK)

        # -- Forma 2: a organização confirma ----------------------------------
        atividade = dados_entrada["atividade"]

        if not pode_checkin_apoio(request.user, atividade.evento):
            return Response(
                {"detail": "Você não organiza o evento nem é da equipe de apoio dele."},
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

        dados = PresencaSerializer(
            presenca, context=self.get_serializer_context()
        ).data
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
        if not pode_checkin_apoio(request.user, presenca.atividade.evento):
            return Response(
                {"detail": "Você não organiza o evento nem é da equipe de apoio dele."},
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


class MeuPerfilView(APIView):
    """GET/PATCH /api/v1/meu-perfil/ — o próprio usuário (token) e seus metadados.

    PATCH parcial edita nome, sobrenome, telefone, endereço e `metadados`.
    E-mail e CPF são somente-leitura (identidade da conta).
    """

    permission_classes = [IsAuthenticated]
    serializer_class = MeuPerfilSerializer

    @extend_schema(responses=MeuPerfilSerializer)
    def get(self, request):
        return Response(MeuPerfilSerializer(request.user).data)

    @extend_schema(request=MeuPerfilSerializer, responses=MeuPerfilSerializer)
    def patch(self, request):
        serializer = MeuPerfilSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MetadadosConfigView(APIView):
    """GET /api/v1/metadados/ — o schema dos metadados configurados por escola.

    Exige organizador: é a referência que o MCP/LLM usa para saber as chaves,
    opções, dependências (`depende_de`) e condicionais (`visivel_quando`).
    """

    permission_classes = [IsOrganizadorEstrito]

    @extend_schema(
        responses=OpenApiResponse(description="Schema dos metadados (campos, opções e condicionais).")
    )
    def get(self, request):
        from eventos import metadados

        return Response({"campos": metadados.campos()})


class ImportarMetadadosView(APIView):
    """POST /api/v1/participantes/importar-metadados/ — upsert por e-mail (organizador).

    Mesmo contrato do CSV da tela do organizador, em JSON: cada linha é
    `{email, <chave>: valor}`. Devolve o relatório por linha
    (atualizado/erro/avisos).
    """

    permission_classes = [IsOrganizadorEstrito]
    serializer_class = ImportarMetadadosSerializer

    @extend_schema(
        request=ImportarMetadadosSerializer,
        responses=OpenApiResponse(description="Relatório por linha (atualizado/erro/avisos)."),
    )
    def post(self, request):
        from eventos import importacao

        entrada = ImportarMetadadosSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        relatorio = importacao.importar_linhas(entrada.validated_data["linhas"])
        return Response(relatorio)


# ---------------------------------------------------------------------------
# Chamada de proposições — catálogo, grade e propostas
#
# As regras vivem em `eventos.propostas` (janela, vaga livre, conflitos, limite
# por pessoa, e-mail/socket no commit). Aqui é a porta de entrada: a API e a
# tela contam a mesma história.
# ---------------------------------------------------------------------------


class EspacoViewSet(viewsets.ModelViewSet):
    """Catálogo de espaços da escola (reaproveitado pelos eventos)."""

    queryset = Espaco.objects.all().order_by("nome")
    serializer_class = EspacoSerializer
    permission_classes = [AllowAny, IsOrganizador]
    search_fields = ["nome"]

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsOrganizador()]


class VagaViewSet(viewsets.ModelViewSet):
    """Grade de oferta: o que o proponente pode reservar."""

    serializer_class = VagaSerializer
    permission_classes = [IsAuthenticated, IsOrganizador]
    queryset = Vaga.objects.none()  # idem: tipa o `{id}` na doc

    def get_queryset(self):
        base = (
            Vaga.objects.select_related("espaco", "evento")
            .order_by("inicio", "espaco__nome")
        )
        parametros = self.request.query_params
        if parametros.get("evento"):
            base = base.filter(evento_id=parametros["evento"])
        if self.request.query_params.get("espaco"):
            base = base.filter(espaco_id=parametros["espaco"])

        usuario = self.request.user
        if usuario.is_staff or usuario.is_superuser:
            return base
        # 2.3.0: a flag de organizador não abre evento alheio. Quem gerencia vê a
        # grade dos seus eventos; o proponente (sem a flag) continua lendo a
        # grade para escolher a vaga (`API.md:164`, fluxo do MCP).
        if getattr(usuario, "is_organizador", False):
            evento_id = parametros.get("evento")
            if evento_id:
                evento = Evento.objects.filter(pk=evento_id).first()
                if evento is not None and not pode_gerenciar_evento(usuario, evento):
                    raise PermissionDenied("Você não gerencia este evento.")
            return base.filter(
                Q(evento__organizador=usuario) | Q(evento__organizadores=usuario)
            ).distinct()
        return base

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        if self.action == "create":
            return [IsOrganizador()]
        return [IsOrganizador(), IsDonoEvento()]

    def get_object(self):
        obj = super().get_object()
        # Edição/exclusão exige dono do evento ou superuser.
        if self.action in ("update", "partial_update", "destroy"):
            self.check_object_permissions(self.request, obj)
        return obj


class PropostaViewSet(viewsets.ModelViewSet):
    """Propostas de atividade: o participante propõe; o organizador decide.

    - GET: o participante vê as próprias; quem organiza vê todas (com
      `?evento=`, `?situacao=` e `?minhas=1`).
    - POST: propõe (janela aberta, vaga livre, sem conflito — tudo do serviço).
    - PATCH: o autor edita enquanto pendente e com a chamada aberta.
    - DELETE: o autor cancela enquanto pendente.
    - POST /aprovar/ e /rejeitar/: decisão do organizador (rejeitar exige motivo).
    """

    serializer_class = AtividadeSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "put", "patch", "delete", "head", "options"]
    queryset = Atividade.objects.none()  # idem: tipa o `{id}` na doc

    def _gerencia(self, evento) -> bool:
        return pode_gerenciar_evento(self.request.user, evento)

    def _ve_tudo(self) -> bool:
        usuario = self.request.user
        return bool(
            usuario.is_staff
            or usuario.is_superuser
            or getattr(usuario, "is_organizador", False)
        )

    def get_queryset(self):
        base = (
            Atividade.objects.filter(proponente__isnull=False)
            .select_related("evento", "tipo", "vaga", "vaga__espaco", "proponente")
            .prefetch_related("palestrantes")
            .order_by("-date_created", "-id")
        )
        parametros = self.request.query_params
        if parametros.get("evento"):
            base = base.filter(evento_id=parametros["evento"])
        if parametros.get("situacao"):
            base = base.filter(situacao=parametros["situacao"])
        if parametros.get("minhas") in ("1", "true", "True"):
            return base.filter(proponente=self.request.user)
        if self._ve_tudo():
            return base
        return base.filter(proponente=self.request.user)

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return PropostaWriteSerializer
        return AtividadeSerializer

    def _resposta(self, proposta):
        return Response(
            AtividadeSerializer(proposta, context={"request": self.request}).data
        )

    def create(self, request, *args, **kwargs):
        entrada = PropostaWriteSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        evento = dados["vaga"].evento
        try:
            proposta = propostas.propor(
                request.user, evento,
                vaga=dados["vaga"],
                titulo=dados["titulo"],
                descricao=dados["descricao"],
                tipo=dados.get("tipo"),
                tipo_sugerido=dados.get("tipo_sugerido", ""),
                palestrantes=dados.get("palestrantes") or [],
                n_vagas=dados.get("n_vagas") or 0,
                emite_certificado=dados.get("emite_certificado", False),
                imagem=dados.get("imagem"),
            )
        except PropostaBloqueada as erro:
            return Response(
                {"detail": erro.messages[0]}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            AtividadeSerializer(proposta, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        proposta = self.get_object()
        if proposta.proponente_id != request.user.pk and not self._gerencia(proposta.evento):
            return Response(
                {"detail": "Só quem propôs edita a proposta."},
                status=status.HTTP_403_FORBIDDEN,
            )

        entrada = PropostaWriteSerializer(data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        try:
            proposta = propostas.atualizar(
                proposta,
                vaga=dados.get("vaga") or proposta.vaga,
                titulo=dados.get("titulo", proposta.titulo),
                descricao=dados.get("descricao", proposta.descricao),
                tipo=dados.get("tipo", proposta.tipo),
                tipo_sugerido=dados.get("tipo_sugerido", proposta.tipo_sugerido),
                palestrantes=(
                    list(dados["palestrantes"]) if "palestrantes" in dados
                    else list(proposta.palestrantes.all())
                ),
                n_vagas=dados.get("n_vagas", proposta.n_vagas),
                emite_certificado=dados.get(
                    "emite_certificado", proposta.emite_certificado
                ),
                imagem=dados.get("imagem"),
            )
        except PropostaBloqueada as erro:
            return Response(
                {"detail": erro.messages[0]}, status=status.HTTP_400_BAD_REQUEST
            )
        return self._resposta(proposta)

    def destroy(self, request, *args, **kwargs):
        """Quem propôs desiste enquanto pendente; quem gerencia apaga sempre.

        O organizador já podia excluir a atividade pela programação, então
        negar aqui só criava um 403 confuso. Depois de decidida, a palavra é
        dele — é o que o próprio serviço documenta.
        """
        proposta = self.get_object()
        if self._gerencia(proposta.evento):
            propostas.remover(proposta)
            return Response(status=status.HTTP_204_NO_CONTENT)
        if proposta.proponente_id != request.user.pk:
            return Response(
                {"detail": "Só quem propôs pode cancelar a proposta."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            propostas.cancelar(proposta)
        except PropostaBloqueada as erro:
            return Response(
                {"detail": erro.messages[0]}, status=status.HTTP_400_BAD_REQUEST
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=DecisaoPropostaSerializer)
    @action(detail=True, methods=["post"])
    def aprovar(self, request, pk=None):
        """Aprova a proposta (por padrão já publica na programação)."""
        proposta = self.get_object()
        if not self._gerencia(proposta.evento):
            return Response(
                {"detail": "Você não organiza este evento."},
                status=status.HTTP_403_FORBIDDEN,
            )
        entrada = DecisaoPropostaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            propostas.aprovar(
                proposta, request.user,
                publicar=entrada.validated_data.get("publicar", True),
                tipo=entrada.validated_data.get("tipo"),
            )
        except PropostaBloqueada as erro:
            return Response(
                {"detail": erro.messages[0]}, status=status.HTTP_400_BAD_REQUEST
            )
        return self._resposta(proposta)

    @extend_schema(request=RejeicaoPropostaSerializer)
    @action(detail=True, methods=["post"])
    def rejeitar(self, request, pk=None):
        """Rejeita a proposta (o motivo é obrigatório) e libera a vaga."""
        proposta = self.get_object()
        if not self._gerencia(proposta.evento):
            return Response(
                {"detail": "Você não organiza este evento."},
                status=status.HTTP_403_FORBIDDEN,
            )
        entrada = RejeicaoPropostaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            propostas.rejeitar(
                proposta, request.user, entrada.validated_data.get("motivo")
            )
        except PropostaBloqueada as erro:
            return Response(
                {"detail": erro.messages[0]}, status=status.HTTP_400_BAD_REQUEST
            )
        return self._resposta(proposta)
