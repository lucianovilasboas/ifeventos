from rest_framework import serializers

from eventos import metadados as metadados_config
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
from eventos.validators import apenas_digitos


class MetadadosField(serializers.DictField):
    """Campo dos metadados configuráveis do participante (dict chave → valor).

    Leitura: devolve o dicionário salvo. Escrita: valida pela MESMA regra do
    formulário e da importação (`eventos/metadados.py`) — obrigatório só quando
    visível, opções do curso, dependência — e descarta campos ocultos.
    """

    def get_attribute(self, instance):
        # Ignora o atributo do model (relação reversa) e lê o JSON de uma vez.
        return metadados_config.dados_de(instance)

    def to_representation(self, value):
        return dict(value) if value else {}

    def to_internal_value(self, data):
        if data in (None, ""):
            return {}
        if not isinstance(data, dict):
            raise serializers.ValidationError("Envie um objeto {chave: valor}.")
        dados, erros = metadados_config.limpar(data)
        if erros:
            raise serializers.ValidationError(erros)
        return dados


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

    def get_nome_completo(self, obj) -> str:
        name = (obj.first_name or "") + " " + (obj.last_name or "")
        return name.strip() or obj.username or obj.email

    def get_foto_url(self, obj) -> str | None:
        return obj.get_foto_url() if hasattr(obj, "get_foto_url") else None


class PalestranteSerializer(serializers.ModelSerializer):
    """Leitura de palestrante para gestão — inclui dados pessoais (PII).

    Só é servido sob `IsOrganizadorEstrito`; não é catálogo público.
    """

    nome_completo = serializers.SerializerMethodField()
    foto_url = serializers.SerializerMethodField()
    metadados = MetadadosField(required=False)

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
            "metadados",
        ]

    def get_nome_completo(self, obj) -> str:
        name = (obj.first_name or "") + " " + (obj.last_name or "")
        return name.strip() or obj.username or obj.email

    def get_foto_url(self, obj) -> str | None:
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
    metadados = MetadadosField(required=False)

    class Meta:
        model = Participante
        fields = ["id", "first_name", "last_name", "email", "cpf", "telefone",
                  "endereco", "metadados"]

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


class VagaResumoSerializer(serializers.ModelSerializer):
    """A vaga da grade de oferta reservada por uma proposta/atividade."""

    espaco = serializers.CharField(source="espaco.nome", read_only=True)
    ocupadas = serializers.IntegerField(read_only=True)
    vagas_restantes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Vaga
        fields = ["id", "espaco", "inicio", "fim", "capacidade", "ocupadas",
                  "vagas_restantes"]


class AtividadeSerializer(serializers.ModelSerializer):
    tipo = TipoAtividadeSerializer(read_only=True)
    palestrantes = ParticipanteResumoSerializer(many=True, read_only=True)
    vagas_disponiveis = serializers.IntegerField(read_only=True)
    imagem_url = serializers.SerializerMethodField()
    # Ciclo de vida: o que separa rascunho, proposta e atividade publicada. Sem
    # isto, quem consome a API recebia tudo misturado e sem como distinguir.
    situacao_rotulo = serializers.CharField(source="get_situacao_display", read_only=True)
    vaga = VagaResumoSerializer(read_only=True)
    proponente = serializers.SerializerMethodField()

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
            # --- ciclo rascunho/proposta (novos) ---
            "publicada",
            "situacao",
            "situacao_rotulo",
            "proponente",
            "vaga",
            "tipo_sugerido",
            "motivo_rejeicao",
        ]

    def get_proponente(self, obj) -> dict | None:
        """Quem propôs — só para quem organiza (ou para o próprio proponente).

        É dado pessoal: o público enxerga a atividade aprovada, não a autoria
        da proposta. `None` também quando a atividade não veio de proposta.
        """
        if not obj.proponente_id:
            return None
        request = self.context.get("request")
        usuario = getattr(request, "user", None)
        if usuario is None or not usuario.is_authenticated:
            return None
        organiza = (
            usuario.is_staff
            or usuario.is_superuser
            or getattr(usuario, "is_organizador", False)
        )
        if not organiza and obj.proponente_id != usuario.pk:
            return None
        return ParticipanteResumoSerializer(obj.proponente).data

    def get_imagem_url(self, obj) -> str | None:
        if hasattr(obj, "get_url_imagem"):
            return obj.get_url_imagem() if not obj.pk else obj.imagem.url if obj.imagem else None
        return None


class EventoSerializer(serializers.ModelSerializer):
    organizador = ParticipanteResumoSerializer(read_only=True)
    atividades = AtividadeSerializer(many=True, read_only=True)
    imagem_url = serializers.SerializerMethodField()
    n_inscricoes = serializers.SerializerMethodField()
    n_atividades = serializers.SerializerMethodField()
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
            "n_atividades",
            "created_at",
            "updated_at",
        ]

    def get_imagem_url(self, obj) -> str | None:
        # Sem imagem, devolve null. O antigo get_url_imagem() apontava para
        # /media/eventos/default.jpg, arquivo que não existe no projeto: quem
        # consumia a API recebia uma URL que sempre respondia 404.
        return obj.imagem.url if obj.imagem else None

    def get_n_inscricoes(self, obj) -> int:
        return obj.get_n_inscricoes()

    def get_n_atividades(self, obj) -> int:
        # O viewset já anota `n_atividades`; o fallback cobre usos avulsos.
        anotado = getattr(obj, "n_atividades", None)
        return anotado if anotado is not None else obj.atividades.count()


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

    def get_pdf_url(self, obj) -> str | None:
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

    `vaga` (opcional) reserva uma janela da grade de oferta: quando vem, o
    local e o horário da atividade passam a ser os DA VAGA (não se digita um
    horário que não bate com a reserva) e a vaga precisa estar livre. Assim a
    API não cria atividade "por fora" da grade — que era o furo por onde duas
    atividades podiam acabar na mesma sala/horário. Sem `vaga`, os três campos
    continuam obrigatórios e valem como no formulário do site.

    `id` entra como somente-leitura (mesmo motivo do EventoWriteSerializer): a
    resposta do POST/PUT/PATCH precisa dizer QUAL atividade foi criada/alterada
    — antes o cliente ficava sem saber (o MCP contornava comparando os ids antes
    e depois).
    """

    id = serializers.IntegerField(read_only=True)

    palestrantes = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Participante.objects.filter(is_palestrante=True),
        # Exposições/feira de livros podem não ter palestrante formal.
        required=False,
    )

    vaga = serializers.PrimaryKeyRelatedField(
        queryset=Vaga.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Atividade
        fields = [
            "id",
            "evento",
            "titulo",
            "descricao",
            "local",
            "tipo",
            "palestrantes",
            "vaga",
            "data_hora_inicio",
            "data_hora_fim",
            "n_vagas",
            "emite_certificado",
            "imagem",
            # Publicar/despublicar pela API (espelha o botão do site). Opcional
            # para não quebrar cliente que já cria atividade sem o campo.
            "publicada",
        ]
        extra_kwargs = {
            "imagem": {"required": False, "allow_null": True},
            "publicada": {"required": False},
            # Sem `vaga` os três são cobrados no validate; com `vaga` eles vêm dela.
            "local": {"required": False},
            "data_hora_inicio": {"required": False},
            "data_hora_fim": {"required": False},
        }

    def validate(self, attrs):
        vaga = attrs.get("vaga", getattr(self.instance, "vaga", None))
        if vaga is not None:
            if vaga.propostas_ativas(ignorar=self.instance).count() >= vaga.capacidade:
                raise serializers.ValidationError(
                    {"vaga": f"A vaga de {vaga} já está ocupada. Escolha outra."}
                )
            # A vaga manda: local e janela saem dela (nada de horário divergente).
            attrs["local"] = vaga.espaco.nome
            attrs["data_hora_inicio"] = vaga.inicio
            attrs["data_hora_fim"] = vaga.fim
            return attrs

        def atual(campo):
            valor = attrs.get(campo)
            if valor is None and self.instance is not None:
                valor = getattr(self.instance, campo, None)
            return valor

        for campo, rotulo in (
            ("local", "Informe o local (ou escolha uma vaga da grade)."),
            ("data_hora_inicio", "Informe o início (ou escolha uma vaga da grade)."),
            ("data_hora_fim", "Informe o término (ou escolha uma vaga da grade)."),
        ):
            if not atual(campo):
                raise serializers.ValidationError({campo: rotulo})

        inicio, fim = atual("data_hora_inicio"), atual("data_hora_fim")
        if inicio and fim and fim <= inicio:
            raise serializers.ValidationError(
                {"data_hora_fim": "O término precisa ser depois do início."}
            )
        return attrs


class TipoAtividadeWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoAtividade
        fields = ["nome"]


class InscricaoCreateSerializer(serializers.ModelSerializer):
    """Faz a self-inscrição do usuário autenticado.

    Mesma regra de negócio da view `participante.inscrever` do site:
    - já inscrito -> erro
    - sem vagas  -> erro
    - conflito de horário -> erro (via `eventos.inscricoes.conflito_com_inscricoes`)
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

        # 3) Conflito de horário — mesma regra da tela (fonte única em
        # `eventos.inscricoes`): antes a comparação estava duplicada aqui e
        # podia divergir da tela a cada mudança.
        from eventos.inscricoes import conflito_com_inscricoes

        conflito = conflito_com_inscricoes(participante, atividade)
        if conflito is not None:
            raise serializers.ValidationError(
                f"Conflito de horário com '{conflito.titulo}'.",
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


class MeuPerfilSerializer(serializers.ModelSerializer):
    """Perfil do usuário autenticado (GET/PATCH em /meu-perfil/).

    Edita nome, sobrenome, telefone, endereço e metadados. E-mail e CPF ficam
    somente-leitura — são a identidade (única) da conta.
    """

    nome_completo = serializers.SerializerMethodField()
    foto_url = serializers.SerializerMethodField()
    metadados = MetadadosField(required=False)

    class Meta:
        model = Participante
        fields = [
            "id",
            "nome_completo",
            "first_name",
            "last_name",
            "email",
            "cpf",
            "telefone",
            "endereco",
            "foto_url",
            "is_participante",
            "is_palestrante",
            "is_organizador",
            "metadados",
        ]
        read_only_fields = [
            "id",
            "nome_completo",
            "email",
            "cpf",
            "foto_url",
            "is_participante",
            "is_palestrante",
            "is_organizador",
        ]

    def get_nome_completo(self, obj) -> str:
        name = (obj.first_name or "") + " " + (obj.last_name or "")
        return name.strip() or obj.username or obj.email

    def get_foto_url(self, obj) -> str | None:
        return obj.get_foto_url() if hasattr(obj, "get_foto_url") else None

    def update(self, instance, validated_data):
        novos = validated_data.pop("metadados", None)
        instance = super().update(instance, validated_data)
        if novos is not None:
            metadados_config.salvar(instance, novos)
        return instance


class ImportarMetadadosSerializer(serializers.Serializer):
    """Corpo do POST /participantes/importar-metadados/ (mesmo contrato do CSV).

    Cada linha é um dicionário `{email, <chave>: valor}`; a pessoa precisa
    existir (chave = e-mail). O processamento usa `eventos/importacao.py`.
    """

    linhas = serializers.ListField(
        child=serializers.DictField(),
        allow_empty=False,
        help_text="Lista de {email, <chave>: valor}, igual às linhas do CSV.",
    )


class ChamadaProposicoesSerializer(serializers.ModelSerializer):
    """Janela de proposições do evento (leitura).

    `vagas_livres` vem junto de propósito: é o que a tela do proponente precisa
    para montar a grade de escolha — e o endpoint é o mesmo que diz se a
    chamada está aberta.
    """

    aberta_agora = serializers.SerializerMethodField()
    vagas_livres = serializers.SerializerMethodField()

    class Meta:
        model = ChamadaProposicoes
        fields = ["id", "titulo", "descricao", "inicio", "fim", "aberta",
                  "aberta_agora", "vagas_livres"]

    def get_aberta_agora(self, obj) -> bool:
        return obj.esta_aberta()

    def get_vagas_livres(self, obj) -> list:
        from eventos import propostas

        return VagaResumoSerializer(
            propostas.vagas_livres(obj.evento), many=True
        ).data


class ChamadaProposicoesWriteSerializer(serializers.ModelSerializer):
    """Abre/encerra a chamada (organizador dono do evento)."""

    class Meta:
        model = ChamadaProposicoes
        fields = ["titulo", "descricao", "inicio", "fim", "aberta"]

    def validate(self, attrs):
        inicio = attrs.get("inicio") or getattr(self.instance, "inicio", None)
        fim = attrs.get("fim") or getattr(self.instance, "fim", None)
        if inicio and fim and fim <= inicio:
            raise serializers.ValidationError(
                {"fim": "O encerramento precisa ser depois da abertura."}
            )
        return attrs


class EspacoSerializer(serializers.ModelSerializer):
    """Espaço do catálogo da escola (leitura e escrita)."""

    def validate_nome(self, value):
        nome = " ".join((value or "").split())
        if not nome:
            raise serializers.ValidationError("Informe o nome do espaço.")
        return nome

    class Meta:
        model = Espaco
        fields = ["id", "nome", "capacidade"]


class VagaSerializer(serializers.ModelSerializer):
    """Vaga da grade: usa as MESMAS regras da tela (`propostas.validar_vaga`)."""

    espaco_nome = serializers.CharField(source="espaco.nome", read_only=True)
    ocupadas = serializers.IntegerField(read_only=True)
    livre = serializers.BooleanField(read_only=True)

    class Meta:
        model = Vaga
        fields = ["id", "evento", "espaco", "espaco_nome", "inicio", "fim",
                  "capacidade", "ocupadas", "livre"]
        extra_kwargs = {"capacidade": {"required": False}}

    def validate(self, attrs):
        from eventos import propostas

        evento = attrs.get("evento") or getattr(self.instance, "evento", None)
        espaco = attrs.get("espaco") or getattr(self.instance, "espaco", None)
        inicio = attrs.get("inicio") or getattr(self.instance, "inicio", None)
        fim = attrs.get("fim") or getattr(self.instance, "fim", None)
        capacidade = attrs.get("capacidade", getattr(self.instance, "capacidade", 1))
        erros = propostas.validar_vaga(
            evento, espaco=espaco, inicio=inicio, fim=fim,
            capacidade=capacidade, instancia=self.instance,
        )
        if erros:
            raise serializers.ValidationError(erros)
        return attrs


class PropostaWriteSerializer(serializers.Serializer):
    """Payload da proposta — o cadastro em si é feito por `propostas.propor`.

    Os campos espelham o formulário do site. O horário/espaço NÃO vêm soltos:
    vêm da vaga escolhida na grade (é o que garante "quem propõe primeiro leva").
    """

    vaga = serializers.PrimaryKeyRelatedField(queryset=Vaga.objects.all())
    titulo = serializers.CharField(max_length=255)
    descricao = serializers.CharField()
    tipo = serializers.PrimaryKeyRelatedField(
        queryset=TipoAtividade.objects.all(), required=False, allow_null=True
    )
    tipo_sugerido = serializers.CharField(
        max_length=60, required=False, allow_blank=True
    )
    palestrantes = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Participante.objects.all(), required=False
    )
    n_vagas = serializers.IntegerField(required=False, min_value=0, default=0)
    emite_certificado = serializers.BooleanField(required=False, default=False)
    imagem = serializers.ImageField(required=False, allow_null=True)

    def validate(self, attrs):
        # Tipo: obrigatório na criação; na edição parcial só quando informado.
        if not self.partial or "tipo" in attrs or "tipo_sugerido" in attrs:
            if not attrs.get("tipo") and not (attrs.get("tipo_sugerido") or "").strip():
                raise serializers.ValidationError(
                    {"tipo": "Escolha um tipo da lista ou sugira um novo."}
                )
        vaga = attrs.get("vaga")
        if vaga is not None and not vaga.livre:
            raise serializers.ValidationError(
                {"vaga": f"A vaga de {vaga} já está ocupada. Escolha outra."}
            )
        return attrs


class DecisaoPropostaSerializer(serializers.Serializer):
    """Corpo da aprovação: publicar (padrão sim) e o tipo oficial, se houver."""

    publicar = serializers.BooleanField(required=False, default=True)
    tipo = serializers.PrimaryKeyRelatedField(
        queryset=TipoAtividade.objects.all(), required=False, allow_null=True
    )


class GradeVagasSerializer(serializers.Serializer):
    """Payload do gerador de grade em lote (o mesmo da tela, estruturado).

    Na tela os blocos vêm numa caixa de texto; aqui vêm como lista, mas o
    parsing é o MESMO (`propostas.parse_blocos`) — nenhuma regra duplicada.
    """

    dias = serializers.ListField(child=serializers.DateField())
    blocos = serializers.ListField(
        child=serializers.CharField(),
        help_text="Cada item no formato HH:MM-HH:MM (ex.: 08:00-10:00).",
    )
    espacos = serializers.PrimaryKeyRelatedField(
        queryset=Espaco.objects.all(), many=True
    )
    capacidade = serializers.IntegerField(required=False, min_value=1, default=1)

    def validate(self, attrs):
        from eventos import propostas

        evento = self.context.get("evento")
        if not attrs.get("dias"):
            raise serializers.ValidationError({"dias": "Escolha pelo menos um dia."})
        if evento is not None:
            for dia in attrs["dias"]:
                if not (evento.data_inicio <= dia <= evento.data_fim):
                    raise serializers.ValidationError(
                        {"dias": f"{dia.strftime('%d/%m/%Y')} está fora do período do evento."}
                    )
        try:
            attrs["blocos_limpos"] = propostas.parse_blocos("\n".join(attrs["blocos"]))
        except ValueError as erro:
            raise serializers.ValidationError({"blocos": str(erro)})
        return attrs


class RejeicaoPropostaSerializer(serializers.Serializer):
    """Corpo da rejeição: o motivo é obrigatório (é o retorno ao proponente)."""

    motivo = serializers.CharField(
        help_text="Explicação que o proponente recebe (obrigatória)."
    )
