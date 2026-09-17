import re
from datetime import date, time

from django.utils import timezone

from django import forms
from .models import Evento, Participante, TipoAtividade
from .models import sem_acento, categorias_conhecidas
from .models import Atividade, ChamadaProposicoes, Espaco, Vaga
from .propostas import dias_do_evento
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy
from django.utils.safestring import mark_safe

from allauth.account.forms import SignupForm as AllauthSignupForm

from .validators import validar_cpf


# -- Formulário para criação de evento --

class EventoForm(forms.ModelForm):
    # Categoria (é o "tema" que a landing usa nos filtros por assunto).
    # Campo de TEXTO com lista de sugestões (o `datalist` é montado no
    # template): o organizador escolhe uma categoria existente ou escreve uma
    # nova, que passa a existir no banco e ganha filtro próprio na landing.
    categoria = forms.CharField(
        label="Categoria",
        required=True,
        max_length=60,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "list": "listaCategorias",
            "autocomplete": "off",
            "placeholder": "Escolha uma categoria ou escreva uma nova",
        }),
    )

    class Meta:
        model = Evento
        fields = ['title', 'description', 'data_inicio', 'data_fim', 'local', 'categoria', 'imagem']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control','style': 'max-height: 100px; overflow-y: auto;'}),
            'data_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'data_fim': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'local': forms.TextInput(attrs={'class': 'form-control'}),
            'imagem': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Sugestões do datalist: lista-semente + categorias já criadas.
        self.categorias_sugeridas = categorias_conhecidas()
        # Ao editar, o campo mostra o rótulo amigável em vez do valor interno
        # (ex.: "Tecnologia" no lugar de "tecnologia").
        if getattr(self.instance, "pk", None):
            self.initial["categoria"] = self.instance.get_categoria_display()

    def clean_categoria(self):
        """Normaliza a categoria informada.

        Quando o texto corresponde a uma categoria já conhecida, grava o valor
        canônico (comparação sem acento e sem caixa). Sem isso, "Robotica"
        digitado viraria um filtro separado de "Robótica" na landing.
        """
        texto = " ".join((self.cleaned_data.get("categoria") or "").split())
        if not texto:
            raise forms.ValidationError("Informe a categoria do evento.")
        for valor, rotulo in categorias_conhecidas():
            if sem_acento(texto) in (sem_acento(valor), sem_acento(rotulo)):
                return valor
        return texto[:60]


# class EventoForm(forms.ModelForm):
#     class Meta:
#         model = Evento
#         fields = ['title', 'description', 'data_inicio', 'data_fim', 'local', 'imagem']
#         widgets = {
#             'title': forms.TextInput(attrs={'class': 'form-control'}),
#             'description': forms.Textarea(attrs={'class': 'form-control', 'style': 'max-height: 100px; overflow-y: auto;'}),
#             'data_inicio': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
#             'data_fim': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
#             'local': forms.TextInput(attrs={'class': 'form-control'}),
#             'imagem': forms.ClearableFileInput(attrs={'class': 'form-control'}),
#         }

#     def __init__(self, *args, **kwargs):
#         super(EventoForm, self).__init__(*args, **kwargs)
#         self.fields['data_inicio'].widget.attrs.update({'class': 'form-control col-6 d-inline-block', 'style': 'width: 40%; margin-right: 4%;'})
#         self.fields['data_fim'].widget.attrs.update({'class': 'form-control col-6 d-inline-block', 'style': 'width: 40%;'})




# -- Formulário para criação ativiade --

# class AtividadeForm(forms.ModelForm):

#     class Meta:
#         model = Atividade
#         fields = ['evento','titulo', 'descricao', 'tipo', 'palestrantes','data_hora_inicio', 'data_hora_fim', 'n_vagas', 'n_inscricoes']
#         widgets = { 
#             'evento': forms.Select(attrs={'class': 'form-control'}),
#             'titulo': forms.TextInput(attrs={'class': 'form-control'}),
#             'descricao': forms.Textarea(attrs={'class': 'form-control','style': 'max-height: 100px; overflow-y: auto;'}),
#             'tipo': forms.Select(attrs={'class': 'form-control'}),
#             'palestrantes': forms.SelectMultiple(attrs={'class': 'form-control'}),
#             'data_hora_inicio': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
#             'data_hora_fim': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
#             'n_vagas': forms.NumberInput(attrs={'class': 'form-control'}),
#             'n_inscricoes': forms.NumberInput(attrs={'class': 'form-control'}),
#         }




class AtividadeForm(forms.ModelForm):
    """Formulário de criação/edição de atividade.

    Diferenças em relação ao formato antigo, todas deliberadas:
      - `evento` saiu do formulário: o evento vem da URL e a view força o
        vínculo ao salvar, então o campo só ocupava espaço e podia ser
        trocado sem efeito algum;
      - `n_inscricoes` saiu: o save() do model recalcula esse número a partir
        das inscrições, ou seja, o que se digitava era descartado;
      - `emite_certificado` entrou: o campo existe no model e a página pública
        mostra "Emite certificado/Sem certificado", mas não havia onde marcá-lo
        (todas as atividades ficavam sem certificado).
    """

    # `tipo` e `palestrantes` são declarados aqui (não vêm do model), então o
    # Meta.labels não os alcança: o rótulo precisa ser dado no próprio campo.
    tipo = forms.ModelChoiceField(
        queryset=TipoAtividade.objects.all(),
        label='Tipo de atividade',
        widget=forms.Select(attrs={'class': 'form-select'}),
        # Sem empty_label o select abria com "---------", que não diz o que
        # escolher (era o estado inicial de toda atividade nova).
        empty_label='Selecione o tipo…',
        required=True
    )

    # Select múltiplo com altura fixa: mostra vários nomes de uma vez e rola
    # dentro da caixa, em vez de esticar o formulário quando há muitos
    # palestrantes cadastrados.
    palestrantes = forms.ModelMultipleChoiceField(
        queryset=Participante.objects.filter(is_palestrante=True),
        label='Palestrantes',
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 6}),
        required=True
    )

    class Meta:
        model = Atividade
        fields = [
            'titulo', 'descricao', 'local', 'tipo', 'palestrantes',
            'data_hora_inicio', 'data_hora_fim', 'n_vagas',
            'emite_certificado', 'imagem',
        ]
        labels = {
            'titulo': 'Título',
            'descricao': 'Descrição',
            'local': 'Local',
            'data_hora_inicio': 'Início',
            'data_hora_fim': 'Término',
            'n_vagas': 'Vagas',
            'emite_certificado': 'Emite certificado',
            'imagem': 'Imagem',
        }
        widgets = { 
            'titulo': forms.TextInput(attrs={'class': 'form-control',
                'placeholder': 'Ex.: Oficina de fotografia'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3,
                'placeholder': 'O que vai acontecer, para quem e o que a pessoa leva de lá.'}),
            'local': forms.TextInput(attrs={'class': 'form-control',
                'placeholder': 'Ex.: Auditório, Sala 12 (vazio = local do evento)'}),
            'data_hora_inicio': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'data_hora_fim': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'n_vagas': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'emite_certificado': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'imagem': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        """Impede término anterior ao início (nada validava isso antes)."""
        dados = super().clean()
        inicio = dados.get('data_hora_inicio')
        fim = dados.get('data_hora_fim')
        if inicio and fim and fim <= inicio:
            self.add_error('data_hora_fim', 'O término precisa ser depois do início.')
        return dados









class TipoAtividadeForm(forms.ModelForm):
    class Meta:
        model = TipoAtividade
        fields = ['nome']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
        } 



class PalestranteForm(forms.ModelForm):
    class Meta:
        model = Participante
        fields = ['first_name', 'last_name','email', 'cpf', 'telefone', 'endereco']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}), 
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control'}),
            'telefone': forms.TextInput(attrs={'class': 'form-control'}),
            'endereco': forms.Textarea(attrs={'class': 'form-control'}), 
        }


class MetadadosFormMixin:
    """Acrescenta ao formulário os campos configurados em `METADADOS_PARTICIPANTE`.

    Cada campo vira `meta_<chave>` (evita colisão com campos do model) e fica
    exposto em `form.campos_metadados` (com o BoundField) para os templates.
    A gravação fica em `save_metadados(participante)`, chamada pela view.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .metadados import campos, construir_field, dados_de, nome_do_campo

        instance = getattr(self, "instance", None)
        iniciais = dados_de(instance) if instance is not None else {}

        def valor_atual(chave):
            """Valor do campo agora: do POST (form ligado) ou dos dados salvos."""
            nome = nome_do_campo(chave)
            if self.is_bound:
                return (self.data.get(nome) or "").strip()
            return str(iniciais.get(chave, "") or "").strip()

        self.campos_metadados = []
        for campo in campos():
            nome = nome_do_campo(campo["chave"])
            pai = valor_atual(campo["depende_de"]) if campo["depende_de"] else None
            self.fields[nome] = construir_field(campo, pai)
            if campo["chave"] in iniciais:
                self.initial[nome] = iniciais[campo["chave"]]
            self.campos_metadados.append({"campo": self[nome], **campo})

    def clean(self):
        """Obrigatório só quando visível + valida a dependência entre campos."""
        from .metadados import nome_do_campo, validar, valores_meta

        dados = super().clean()
        for chave, mensagens in validar(valores_meta(dados)).items():
            for mensagem in mensagens:
                self.add_error(nome_do_campo(chave), mensagem)
        return dados

    def save_metadados(self, participante):
        from .metadados import coletar, salvar

        return salvar(participante, coletar(self.cleaned_data))


# ---------------------------------------------------------------------------
# Cadastro de participante (tela /accounts/signup/) — allauth
# ---------------------------------------------------------------------------

class SignupFormComCpf(MetadadosFormMixin, AllauthSignupForm):
    """Cadastro pela web: e-mail + senha + CPF.

    O CPF é OBRIGATÓRIO aqui (mas não no modelo: contas de login social/API
    podem não ter documento). A validação usa os dígitos verificadores e
    devolve erro NO CAMPO — o formulário volta para a tela em vez de estourar
    500 no banco (que era o comportamento antigo, quando o CPF nem era pedido).
    """

    cpf = forms.CharField(
        label="CPF",
        required=True,
        max_length=14,  # aceita com ou sem máscara; normalizamos em seguida
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "000.000.000-00",
                "inputmode": "numeric",
                "autocomplete": "off",
                "maxlength": "14",
            }
        ),
        help_text="Somente números.",
    )

    first_name = forms.CharField(
        label="Nome",
        required=True,
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Seu nome",
                "autocomplete": "given-name",
            }
        ),
    )

    last_name = forms.CharField(
        label="Sobrenome",
        required=False,
        max_length=150,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Seu sobrenome",
                "autocomplete": "family-name",
            }
        ),
    )

    # Ordem de exibição na tela.
    field_order = ["email", "first_name", "last_name", "cpf", "password1", "password2"]

    def clean_first_name(self):
        return " ".join((self.cleaned_data.get("first_name") or "").split())

    def clean_last_name(self):
        return " ".join((self.cleaned_data.get("last_name") or "").split())

    def clean_cpf(self):
        """Valida os dígitos verificadores e devolve o CPF sem máscara."""
        try:
            return validar_cpf(self.cleaned_data.get("cpf"))
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages)

    def save(self, request):
        """Cria a conta pelo allauth e grava CPF, nome e metadados logo depois."""
        user = super().save(request)
        user.cpf = self.cleaned_data["cpf"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data.get("last_name", "")
        user.save(update_fields=["cpf", "first_name", "last_name"])
        self.save_metadados(user)
        return user
 



# ---------------------------------------------------------------------------
# Chamada de proposições de atividades
# ---------------------------------------------------------------------------

class ChamadaProposicoesForm(forms.ModelForm):
    """Janela de proposições do evento (aberta/encerrada pelo organizador)."""

    class Meta:
        model = ChamadaProposicoes
        fields = ["titulo", "descricao", "inicio", "fim", "aberta"]
        labels = {
            "titulo": "Título da chamada",
            "descricao": "Texto de apoio",
            "inicio": "Abre em",
            "fim": "Encerra em",
            "aberta": "Aceitando propostas",
        }
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 3,
                "placeholder": "Explique o que você espera das propostas."}),
            "inicio": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M"),
            "fim": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M"),
            "aberta": forms.CheckboxInput(
                attrs={"class": "form-check-input", "role": "switch"}),
        }

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("inicio"), dados.get("fim")
        if inicio and fim and fim <= inicio:
            self.add_error("fim", "O encerramento precisa ser depois da abertura.")
        return dados


class EspacoForm(forms.ModelForm):
    """Espaço no catálogo da escola, reaproveitado pelos eventos.

    O `datalist` com os nomes já conhecidos fica no template; aqui a checagem é
    a que vale: não deixa criar "Auditorio" quando já existe "Auditório".
    """

    class Meta:
        model = Espaco
        fields = ["nome", "capacidade"]
        labels = {"nome": "Espaço", "capacidade": "Capacidade (lugares)"}
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control",
                "autocomplete": "off", "list": "listaEspacos",
                "placeholder": "Ex.: Auditório, Laboratório 2"}),
            "capacidade": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
        }

    def clean_nome(self):
        nome = " ".join((self.cleaned_data.get("nome") or "").split())
        if not nome:
            return nome
        outros = Espaco.objects.exclude(pk=getattr(self.instance, "pk", None))
        chave = sem_acento(nome)
        for existente in outros.values_list("nome", flat=True):
            if sem_acento(existente) == chave:
                raise forms.ValidationError(
                    f"Esse espaço já está no catálogo como '{existente}' — "
                    "escolha ele na lista."
                )
        return nome


class VagaForm(forms.ModelForm):
    """Vaga da grade: dia + horário + espaço que o proponente pode reservar."""

    class Meta:
        model = Vaga
        fields = ["espaco", "inicio", "fim", "capacidade"]
        labels = {
            "espaco": "Espaço",
            "inicio": "Início",
            "fim": "Término",
            "capacidade": "Atividades simultâneas",
        }
        widgets = {
            "espaco": forms.Select(attrs={"class": "form-select"}),
            "inicio": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M"),
            "fim": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M"),
            "capacidade": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
        }

    def __init__(self, *args, evento=None, **kwargs):
        super().__init__(*args, **kwargs)
        # O espaço vem do catálogo da escola (não é exclusivo do evento): é o
        # que faz "Auditório" ser o mesmo lugar em todos os eventos.
        self.evento = evento
        self.fields["espaco"].queryset = Espaco.objects.all()
        # Sem a opção vazia: o espaço é obrigatório e o catálogo já está
        # selecionado no primeiro item (o "---------" só poluía o select).
        self.fields["espaco"].empty_label = None
        if not Espaco.objects.exists():
            self.fields["espaco"].help_text = (
                "Cadastre um espaço antes de criar vagas."
            )

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get("inicio"), dados.get("fim")
        if inicio and fim and fim <= inicio:
            self.add_error("fim", "O término precisa ser depois do início.")
            return dados

        if inicio and self.evento is not None:
            dia = timezone.localtime(inicio).date()
            if not (self.evento.data_inicio <= dia <= self.evento.data_fim):
                self.add_error(
                    "inicio", "O dia da vaga precisa estar dentro do período do evento."
                )

        espaco = dados.get("espaco")
        if espaco and inicio and fim:
            # A constraint é global (a sala não pode ter duas vagas idênticas):
            # aqui a mensagem sai legível em vez do erro cru do banco.
            repetida = Vaga.objects.filter(espaco=espaco, inicio=inicio, fim=fim)
            if self.instance.pk:
                repetida = repetida.exclude(pk=self.instance.pk)
            if repetida.exists():
                self.add_error(
                    "inicio", "Já existe uma vaga deste espaço nessa janela."
                )

        if self.instance.pk and self.instance.tem_propostas_ativas:
            ocupadas = self.instance.ocupadas
            capacidade = dados.get("capacidade")
            if capacidade is not None and capacidade < ocupadas:
                self.add_error(
                    "capacidade",
                    f"Esta vaga tem {ocupadas} proposta(s) ativa(s): a capacidade "
                    "não pode ficar menor que isso.",
                )
            for campo, novo in (
                ("espaco", espaco), ("inicio", inicio), ("fim", fim),
            ):
                if novo is not None and novo != getattr(self.instance, campo):
                    self.add_error(
                        campo,
                        "Esta vaga já tem proposta: espaço e horário ficam "
                        "travados (a reserva da proposta depende deles).",
                    )
        return dados


class PropostaForm(forms.ModelForm):
    """Proposta de atividade feita por um participante durante a chamada.

    O horário e o espaço NÃO são digitados: vêm da vaga escolhida na grade de
    oferta (é o que garante "quem propõe primeiro leva"). O tipo pode ser
    escolhido do catálogo ou sugerido como texto — o organizador normaliza na
    aprovação, para o catálogo global de tipos não virar terra de ninguém.
    """

    vaga = forms.ModelChoiceField(
        queryset=Vaga.objects.none(),
        label="Dia, horário e espaço",
        empty_label="Selecione a vaga…",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    palestrantes = forms.ModelMultipleChoiceField(
        queryset=Participante.objects.none(),
        label="Palestrantes",
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 6}),
        help_text="Escolha quem já é palestrante — ou marque abaixo que é você.",
    )
    tipo = forms.ModelChoiceField(
        queryset=TipoAtividade.objects.all(),
        label="Tipo de atividade",
        required=False,
        empty_label="Selecione o tipo…",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    tipo_sugerido = forms.CharField(
        label="Sugerir um tipo novo",
        required=False,
        max_length=60,
        widget=forms.TextInput(attrs={
            "class": "form-control", "list": "listaTipos", "autocomplete": "off",
            "placeholder": "Só se nenhum tipo da lista servir",
        }),
    )
    eu_sou_palestrante = forms.BooleanField(
        label="Eu vou ministrar esta atividade",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "role": "switch"}),
    )
    # Não obrigatório de propósito: sem preencher, vale a capacidade do espaço.
    n_vagas = forms.IntegerField(
        label="Vagas para participantes",
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 0}),
    )

    class Meta:
        model = Atividade
        # `vaga`, `tipo`, `tipo_sugerido` e `palestrantes` entram aqui para o
        # formulário de EDIÇÃO receber o valor atual do banco como inicial
        # (declarar o campo não basta: o Django só monta o initial do que está
        # em Meta.fields).
        fields = [
            "titulo", "descricao", "n_vagas", "emite_certificado", "imagem",
            "vaga", "tipo", "tipo_sugerido", "palestrantes",
        ]
        labels = {
            "titulo": "Título",
            "descricao": "Descrição",
            "emite_certificado": "Emite certificado",
            "imagem": "Imagem",
        }
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control",
                "placeholder": "Ex.: Oficina de fotografia"}),
            "descricao": forms.Textarea(attrs={"class": "form-control", "rows": 4,
                "placeholder": "O que vai acontecer, para quem e o que a pessoa leva de lá."}),
            "emite_certificado": forms.CheckboxInput(
                attrs={"class": "form-check-input", "role": "switch"}),
            "imagem": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, evento=None, usuario=None, incluir_vaga=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.evento = evento
        self.usuario = usuario
        if evento is not None:
            livres = [v.pk for v in evento.vagas.select_related("espaco") if v.livre]
            if incluir_vaga is not None and incluir_vaga.pk not in livres:
                livres.append(incluir_vaga.pk)
            self.fields["vaga"].queryset = (
                Vaga.objects.filter(pk__in=livres)
                .select_related("espaco")
                .order_by("inicio", "espaco__nome")
            )

        pessoas = Participante.objects.filter(is_palestrante=True)
        if usuario is not None and getattr(usuario, "pk", None):
            pessoas = pessoas.exclude(pk=usuario.pk)
        self.fields["palestrantes"].queryset = pessoas.order_by("first_name", "last_name")

        # Na edição: já escolhidos (sem o próprio, que é a caixa abaixo) e a
        # caixa "eu vou ministrar" marcada quando ele já estava na atividade.
        if self.instance and self.instance.pk and getattr(usuario, "pk", None):
            atuais = self.instance.palestrantes.all()
            self.fields["palestrantes"].initial = [
                p.pk for p in atuais if p.pk != usuario.pk
            ]
            self.fields["eu_sou_palestrante"].initial = any(
                p.pk == usuario.pk for p in atuais
            )

    def _ocupadas(self, vaga):
        """Propostas ativas na vaga, ignorando esta (na edição)."""
        return vaga.propostas_ativas(ignorar=self.instance).count()

    def clean(self):
        dados = super().clean()
        if not dados.get("tipo") and not (dados.get("tipo_sugerido") or "").strip():
            self.add_error("tipo", "Escolha um tipo da lista ou sugira um novo.")
        vaga = dados.get("vaga")
        if vaga is not None and self._ocupadas(vaga) >= vaga.capacidade:
            self.add_error("vaga", f"A vaga de {vaga} já está ocupada. Escolha outra.")
        return dados

    def aplicar_em(self, atividade):
        """Copia para a atividade os campos que o form entrega prontos."""
        atividade.titulo = self.cleaned_data["titulo"].strip()
        atividade.descricao = self.cleaned_data["descricao"].strip()
        atividade.n_vagas = self.cleaned_data.get("n_vagas") or 0
        atividade.emite_certificado = bool(self.cleaned_data.get("emite_certificado"))
        atividade.tipo = self.cleaned_data.get("tipo")
        atividade.tipo_sugerido = (self.cleaned_data.get("tipo_sugerido") or "").strip()
        if self.cleaned_data.get("imagem"):
            atividade.imagem = self.cleaned_data["imagem"]
        return atividade


class GradeVagasForm(forms.Form):
    """Gera vagas em lote: dias do evento × blocos de horário × espaços.

    Os blocos vêm numa caixa de texto (um por linha) porque é o formato mais
    rápido de colar/editar uma grade de 2 a 6 blocos — e aceita vírgula como
    separador, caso venham numa linha só.
    """

    BLOCO = re.compile(r"^(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})$")

    dias = forms.MultipleChoiceField(
        label="Dias do evento",
        choices=[],
        error_messages={"required": "Escolha pelo menos um dia."},
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
    )
    blocos = forms.CharField(
        label="Horários (um por linha)",
        widget=forms.Textarea(attrs={
            "class": "form-control", "rows": 4,
            "placeholder": "08:00-10:00\n10:00-12:00\n14:00-16:00",
        }),
    )
    espacos = forms.ModelMultipleChoiceField(
        queryset=Espaco.objects.none(),
        label="Espaços",
        error_messages={"required": "Escolha pelo menos um espaço."},
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
    )
    capacidade = forms.IntegerField(
        label="Atividades simultâneas",
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": 1}),
    )

    def __init__(self, *args, evento=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.evento = evento
        if evento is not None:
            self.fields["dias"].choices = dias_do_evento(evento)
        self.fields["espacos"].queryset = Espaco.objects.all()

    def clean_dias(self):
        """Só aceita dias DENTRO do período do evento (o POST pode vir forjado)."""
        escolhidos = self.cleaned_data.get("dias") or []
        dias = [date.fromisoformat(valor) for valor in escolhidos]
        if self.evento is not None:
            for dia in dias:
                if not (self.evento.data_inicio <= dia <= self.evento.data_fim):
                    raise forms.ValidationError(
                        f"{dia.strftime('%d/%m/%Y')} está fora do período do evento."
                    )
        return dias

    def clean_blocos(self):
        texto = (self.cleaned_data.get("blocos") or "").replace(",", "\n")
        blocos, vistas = [], set()
        for numero, linha in enumerate(texto.splitlines(), start=1):
            linha = linha.strip()
            if not linha:
                continue
            achado = self.BLOCO.match(linha)
            if not achado:
                raise forms.ValidationError(
                    f"Linha {numero}: use o formato HH:MM-HH:MM (ex.: 08:00-10:00)."
                )
            hora1, min1, hora2, min2 = (int(valor) for valor in achado.groups())
            try:
                inicio, fim = time(hora1, min1), time(hora2, min2)
            except ValueError:
                raise forms.ValidationError(f"Linha {numero}: horário inválido.")
            if fim <= inicio:
                raise forms.ValidationError(
                    f"Linha {numero}: o término precisa ser depois do início."
                )
            if (inicio, fim) not in vistas:
                vistas.add((inicio, fim))
                blocos.append((inicio, fim))
        if not blocos:
            raise forms.ValidationError("Informe pelo menos um bloco de horário.")
        return blocos
