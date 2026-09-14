from rest_framework import serializers

from eventos.models import Atividade, Certificado, Evento, Inscricao, Participante, Presenca, TipoAtividade
from eventos.validators import apenas_digitos


class ParticipanteResumoSerializer(serializers.ModelSerializer):
    """Dados básicos do participante/palestrante (sem dados sensíveis)."""

    nome_completo = serializers.SerializerMethodField()
    foto_url = serializers.SerializerMethodField()

    class Meta:
        model = Participante
        fields = [
            "id",
            "nome_completo",
            "email",
            "foto_url",
            "is_organizador",
            "is_palestrante",
        ]

    def get_nome_completo(self, obj):
        name = (obj.first_name or "") + " " + (obj.last_name or "")
        return name.strip() or obj.username or obj.email

    def get_foto_url(self, obj):
        return obj.get_foto_url() if hasattr(obj, "get_foto_url") else None


class PalestranteSerializer(serializers.ModelSerializer):
    """Leitura de palestrante para gestão — inclui dados pessoais (PII).

    Só é servido sob `IsOrganizadorEstrito`; não é catálogo público.
    """

    nome_completo = serializers.SerializerMethodField()
    foto_url = serializers.SerializerMethodField()

    class Meta:
        model = Participante
        fields = [
            "id",
            "nome_completo",
            "email",
            "cpf",
            "telefone",
            "endereco",
            "foto_url",
            "is_participante",
            "is_palestrante",
            "is_organizador",
        ]

    def get_nome_completo(self, obj):
        name = (obj.first_name or "") + " " + (obj.last_name or "")
        return name.strip() or obj.username or obj.email

    def get_foto_url(self, obj):
        return obj.get_foto_url() if hasattr(obj, "get_foto_url") else None


class PalestranteWriteSerializer(serializers.ModelSerializer):
    """Criação/atualização de palestrante (Participante com is_palestrante=True).

    Sem `foto`: a API fala JSON e arquivo exige multipart (o MCP também é JSON).
    O e-mail não tem UniqueValidator automático de propósito — o viewset trata
    "e-mail já existente" como atualização idempotente; a unicidade só é cobrada
    no update, quando o e-mail muda para um já usado por OUTRA conta.
    """

    email = serializers.EmailField()
    cpf = serializers.CharField(max_length=14, required=False, allow_blank=True)
    telefone = serializers.CharField(
        max_length=15, required=False, allow_blank=True, allow_null=True
    )
    endereco = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = Participante
        fields = ["id", "first_name", "last_name", "email", "cpf", "telefone", "endereco"]

    def validate_email(self, value):
        if self.instance is None:
            return value
        if (
            Participante.objects.filter(email__iexact=value)
            .exclude(pk=self.instance.pk)
            .exists()
        ):
            raise serializers.ValidationError("E-mail já cadastrado.", code="unique")
        return value

    def validate_cpf(self, value):
        # Guarda só os dígitos — mesma regra do model (Participante.save).
        return apenas_digitos(value)


class TipoAtividadeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoAtividade
        fields = ["id", "nome"]


class AtividadeSerializer(serializers.ModelSerializer):
    tipo = TipoAtividadeSerializer(read_only=True)
    palestrantes = ParticipanteResumoSerializer(many=True, read_only=True)
    vagas_disponiveis = serializers.IntegerField(read_only=True)
    imagem_url = serializers.SerializerMethodField()

    class Meta:
        model = Atividade
        fields = [
            "id",
            "titulo",
            "descricao",
            "local",
            "tipo",
            "palestrantes",
            "data_hora_inicio",
            "data_hora_fim",
            "n_vagas",
            "n_inscricoes",
            "vagas_disponiveis",
            "emite_certificado",
            "imagem_url",
        ]

    def get_imagem_url(self, obj):
        if hasattr(obj, "get_url_imagem"):
            return obj.get_url_imagem() if not obj.pk else obj.imagem.url if obj.imagem else None
        return None


class EventoSerializer(serializers.ModelSerializer):
    organizador = ParticipanteResumoSerializer(read_only=True)
    atividades = AtividadeSerializer(many=True, read_only=True)
    imagem_url = serializers.SerializerMethodField()
    n_inscricoes = serializers.SerializerMethodField()
    categoria_display = serializers.CharField(
        source="get_categoria_display", read_only=True
    )

    class Meta:
        model = Evento
        fields = [
            "id",
            "title",
            "description",
            "local",
            "data_inicio",
            "data_fim",
            "categoria",
            "categoria_display",
            "imagem_url",
            "organizador",
            "atividades",
            "n_inscricoes",
            "created_at",
            "updated_at",
        ]

    def get_imagem_url(self, obj):
        # Sem imagem, devolve null. O antigo get_url_imagem() apontava para
        # /media/eventos/default.jpg, arquivo que não existe no projeto: quem
        # consumia a API recebia uma URL que sempre respondia 404.
        return obj.imagem.url if obj.imagem else None

    def get_n_inscricoes(self, obj):
        return obj.get_n_inscricoes()


class InscricaoSerializer(serializers.ModelSerializer):
    """Inscrição com dados resolvidos para leitura."""

    participante = ParticipanteResumoSerializer(read_only=True)
    atividade = AtividadeSerializer(read_only=True)

    class Meta:
        model = Inscricao
        fields = [
            "id",
            "participante",
            "atividade",
            "confirmada",
            "certificado_emitido",
            "created_at",
            "updated_at",
        ]


class CertificadoSerializer(serializers.ModelSerializer):
    participante = ParticipanteResumoSerializer(read_only=True)
    atividade = AtividadeSerializer(read_only=True)
    evento = EventoSerializer(read_only=True)
    pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = Certificado
        fields = [
            "id",
            "participante",
            "atividade",
            "evento",
            "codigo",
            "data_emissao",
            "pdf_url",
        ]

    def get_pdf_url(self, obj):
        if obj.pdf:
            return obj.pdf.url
        return None


# =============================================================================
# Serializers de ESCRITA (Fase 2) — reutilizam os models/regras do site
# =============================================================================


class EventoWriteSerializer(serializers.ModelSerializer):
    """Criação/atualização de Evento.

    `organizador` NÃO vem do payload: é setado automaticamente ao usuário
    autenticado (via perform_create/update). Espelha os campos de EventoForm.

    `id` entra como somente-leitura para a resposta de POST/PUT/PATCH dizer
    qual evento foi criado/alterado — antes o cliente ficava sem saber.
    """

    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Evento
        fields = [
            "id",
            "title",
            "description",
            "local",
            "data_inicio",
            "data_fim",
            "categoria",
            "imagem",
        ]
        extra_kwargs = {
            "imagem": {"required": False, "allow_null": True},
            # Opcional para não quebrar cliente que já cria evento sem o campo
            # (o model tem default "formacao").
            "categoria": {"required": False},
        }


class AtividadeWriteSerializer(serializers.ModelSerializer):
    """Criação/atualização de Atividade.

    `evento`, `tipo` e `palestrantes` são enviados por ID (como o AtividadeForm
    do site: palestrantes só podem ser is_palestrante=True). `n_inscricoes` é
    read-only (controlado pelo save() do model).
    """

    palestrantes = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Participante.objects.filter(is_palestrante=True),
        # Exposições/feira de livros podem não ter palestrante formal.
        required=False,
    )

    class Meta:
        model = Atividade
        fields = [
            "evento",
            "titulo",
            "descricao",
            "local",
            "tipo",
            "palestrantes",
            "data_hora_inicio",
            "data_hora_fim",
            "n_vagas",
            "emite_certificado",
            "imagem",
        ]
        extra_kwargs = {"imagem": {"required": False, "allow_null": True}}


class TipoAtividadeWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoAtividade
        fields = ["nome"]


class InscricaoCreateSerializer(serializers.ModelSerializer):
    """Faz a self-inscrição do usuário autenticado.

    Replica a regra de negócio da view `participante.inscrever` do site:
    - já inscrito -> erro
    - sem vagas  -> erro
    - conflito de horário -> erro
    `participante` é setado automaticamente a request.user.
    """

    atividade = serializers.PrimaryKeyRelatedField(queryset=Atividade.objects.all())

    class Meta:
        model = Inscricao
        fields = ["atividade"]

    def validate(self, attrs):
        user = self.context["request"].user
        atividade = attrs["atividade"]
        participante = Participante.from_user(user)

        # 1) Já inscrito
        if Inscricao.objects.filter(participante=participante, atividade=atividade).exists():
            raise serializers.ValidationError("Você já está inscrito nesta atividade.", code="duplicate")

        # 2) Vagas
        inscritos = Inscricao.objects.filter(atividade=atividade).count()
        if atividade.n_vagas <= inscritos:
            raise serializers.ValidationError(
                "Lamentamos, mas essa atividade não possui mais vagas.", code="no_vacancy"
            )

        # 3) Conflito de horário (igual à lógica do site)
        from django.utils.timezone import localtime

        atividades_inscritas = Atividade.objects.filter(inscritos__participante=participante)
        for insc in atividades_inscritas:
            if (
                localtime(atividade.data_hora_inicio) < localtime(insc.data_hora_fim)
                and localtime(atividade.data_hora_fim) > localtime(insc.data_hora_inicio)
            ):
                raise serializers.ValidationError(
                    f"Conflito de horário com '{insc.titulo}'.",
                    code="time_conflict",
                )

        attrs["participante"] = participante
        return attrs

class CrachaSerializer(serializers.Serializer):
    """Crachá do usuário em um evento — derivado, não é registro no banco.

    Um por evento em que a pessoa tem papel. `token` é o que vai dentro do QR;
    a imagem do QR sai no endpoint indicado em `qr_png`.
    """

    evento_id = serializers.IntegerField()
    evento = serializers.CharField()
    periodo = serializers.CharField()
    local = serializers.CharField(allow_null=True)
    papel = serializers.CharField(help_text="organizador | palestrante | participante")
    papel_rotulo = serializers.CharField()
    nome = serializers.CharField()
    codigo = serializers.CharField(help_text="Código curto, para quando a câmera não estiver disponível.")
    token = serializers.CharField(help_text="Token assinado que vai dentro do QR.")
    url = serializers.CharField(help_text="URL pública que o QR abre ao ser lido.")
    qr_png = serializers.CharField(help_text="Endpoint que devolve o PNG do QR.")


class VerificacaoSerializer(serializers.Serializer):
    """Resposta da verificação de um crachá ou certificado."""

    valido = serializers.BooleanField()
    erro = serializers.CharField(required=False)
    tipo = serializers.CharField(required=False, help_text="cracha | certificado")
    nome = serializers.CharField(required=False)
    papel = serializers.CharField(required=False, allow_null=True)
    papel_rotulo = serializers.CharField(required=False)
    evento_id = serializers.IntegerField(required=False, allow_null=True)
    evento = serializers.CharField(required=False, allow_null=True)
    periodo = serializers.CharField(required=False, allow_blank=True)
    atividade_id = serializers.IntegerField(required=False, allow_null=True)
    atividade = serializers.CharField(required=False, allow_null=True)


class PresencaSerializer(serializers.ModelSerializer):
    """Presença registrada em uma atividade (o resultado do check-in)."""

    participante = ParticipanteResumoSerializer(read_only=True)
    registrada_por = ParticipanteResumoSerializer(read_only=True)
    atividade = serializers.CharField(source="atividade.titulo", read_only=True)
    atividade_id = serializers.IntegerField(read_only=True)
    evento_id = serializers.IntegerField(source="atividade.evento_id", read_only=True)
    evento = serializers.CharField(source="atividade.evento.title", read_only=True)
    papel_rotulo = serializers.CharField(source="get_papel_display", read_only=True)
    origem_rotulo = serializers.CharField(source="get_origem_display", read_only=True)

    class Meta:
        model = Presenca
        fields = [
            "id",
            "atividade",
            "atividade_id",
            "evento",
            "evento_id",
            "participante",
            "papel",
            "papel_rotulo",
            "origem",
            "origem_rotulo",
            "registrada_por",
            "registrada_em",
        ]


class PresencaCreateSerializer(serializers.Serializer):
    """Payload do check-in: qual atividade + COMO a pessoa foi identificada.

    Aceita três formas porque na portaria as três acontecem: o QR lido da câmera
    (`token`), o código ditado por quem está sem celular (`codigo`) e a marcação
    manual na lista (`participante`).
    """

    atividade = serializers.PrimaryKeyRelatedField(
        queryset=Atividade.objects.all(), required=False
    )
    token_atividade = serializers.CharField(
        required=False, allow_blank=True,
        help_text="Código do QR da atividade: confirmação feita pela própria pessoa.",
    )
    token = serializers.CharField(required=False, allow_blank=True)
    codigo = serializers.CharField(required=False, allow_blank=True)
    participante = serializers.PrimaryKeyRelatedField(
        queryset=Participante.objects.all(), required=False
    )
    origem = serializers.ChoiceField(
        choices=[("qr", "QR do crachá"), ("codigo", "Código digitado"), ("manual", "Marcação manual")],
        required=False,
    )

    def validate(self, attrs):
        # Forma 1 — a própria pessoa confirma com o QR da atividade (fluxo B):
        # quem ela é vem da sessão, então nem precisa identificar a pessoa aqui.
        if attrs.get("token_atividade"):
            return attrs

        # Forma 2 — a organização confirma (lendo o crachá, digitando o código ou
        # marcando na lista): aí a atividade e a pessoa têm de vir no payload.
        if not attrs.get("atividade"):
            raise serializers.ValidationError(
                "Informe 'atividade' (com token, codigo ou participante) ou 'token_atividade'."
            )
        if not any(attrs.get(campo) for campo in ("token", "codigo", "participante")):
            raise serializers.ValidationError(
                "Informe 'token' (QR do crachá), 'codigo' (digitado) ou 'participante' (marcação manual)."
            )
        return attrs


class QrAtividadeSerializer(serializers.Serializer):
    """QR de presença da atividade: o código rotativo que a organização exibe."""

    atividade_id = serializers.IntegerField()
    atividade = serializers.CharField()
    url = serializers.CharField(help_text="URL que o QR abre — é o que a pessoa escaneia.")
    png = serializers.CharField(help_text="QR como data URL, pronto para exibir na tela.")
    validade_segundos = serializers.IntegerField(help_text="Quanto tempo este código vale.")
    renovar_em_segundos = serializers.IntegerField(help_text="De quanto em quanto tempo renovar.")
    janela = serializers.DictField(help_text="Abre em, fecha em, se está aberta agora e por quê.")
