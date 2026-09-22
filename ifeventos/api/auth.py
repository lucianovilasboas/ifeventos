"""Endpoints de autenticação por Token para consumo por app externo/LLM.

O token (DRF authtoken) é emitido trocando-se email+senha do Participante,
reaproveitando a autenticação do sistema (login é feito por email).
"""

from django.contrib.auth import authenticate
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


class RegistroSerializer(serializers.Serializer):
    """Cadastro de novo participante via API (cria conta is_participante=True)."""

    email = serializers.EmailField()
    password = serializers.CharField(min_length=6, trim_whitespace=False)
    cpf = serializers.CharField(max_length=14)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    telefone = serializers.CharField(max_length=15, required=False, allow_blank=True)

    def validate_email(self, value):
        from eventos.models import Participante

        if Participante.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("E-mail já cadastrado.", code="unique")
        return value

    def validate_cpf(self, value):
        # Guarda somente os dígitos (mesma regra do cadastro web e do modelo).
        # O CPF NÃO é mais único: o e-mail é a identidade da conta e um mesmo
        # CPF pode estar ligado a mais de um e-mail.
        return "".join(ch for ch in value if ch.isdigit())


class RegistroView(APIView):
    """POST /api/v1/auth/registro/  -> cria conta e devolve token."""

    authentication_classes = []
    permission_classes = []
    serializer_class = RegistroSerializer

    @extend_schema(
        request=RegistroSerializer,
        responses={201: {"type": "object", "properties": {"token": {"type": "string"}, "user_id": {"type": "integer"}, "email": {"type": "string"}}}},
    )
    def post(self, request, *args, **kwargs):
        serializer = RegistroSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from eventos.models import Participante

        user = Participante.objects.create_user(
            email=data["email"],
            password=data["password"],
            cpf=data["cpf"],
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            telefone=data.get("telefone", ""),
            is_participante=True,
            is_organizador=False,
            is_palestrante=False,
        )
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "token": token.key,
                "user_id": user.pk,
                "email": user.email,
            },
            status=status.HTTP_201_CREATED,
        )


class EmailAuthTokenSerializer(serializers.Serializer):
    """Autentica pelo email (o sistema usa email como USERNAME_FIELD)."""

    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")
        user = authenticate(request=self.context.get("request"), email=email, password=password)
        if not user:
            raise serializers.ValidationError("E-mail ou senha inválidos.", code="authorization")
        if not user.is_active:
            raise serializers.ValidationError("Usuário inativo.", code="authorization")
        attrs["user"] = user
        return attrs


class ObtainTokenView(APIView):
    """POST /api/v1/auth/token/  com {'email': ..., 'password': ...} -> {'token': '...'}"""

    authentication_classes = []
    permission_classes = []
    serializer_class = EmailAuthTokenSerializer
    # Freio anti-força-bruta: sem isto, tentativas erradas em série não mudavam
    # nada. A taxa fica em REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"].
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        request=EmailAuthTokenSerializer,
        responses={200: {"type": "object", "properties": {"token": {"type": "string"}, "user_id": {"type": "integer"}, "email": {"type": "string"}}}},
    )
    def post(self, request, *args, **kwargs):
        serializer = EmailAuthTokenSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "token": token.key,
                "user_id": user.pk,
                "email": user.email,
            },
            status=status.HTTP_200_OK,
        )