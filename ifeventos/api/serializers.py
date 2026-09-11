from rest_framework import serializers

from eventos.models import Atividade, Certificado, Evento, Inscricao, Participante, TipoAtividade


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
        required=True,
    )

    class Meta:
        model = Atividade
        fields = [
            "evento",
            "titulo",
            "descricao",
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