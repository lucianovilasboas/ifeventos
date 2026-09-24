from django.db import models
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.utils.text import slugify
import os
import unicodedata
from datetime import datetime
from PIL import Image
import uuid
from django.utils import timezone
from .managers import ParticipanteManager
from .validators import apenas_digitos


def sem_acento(texto):
    """Minúsculas e sem acento — para comparar rótulos de categoria.

    Faz "Tecnologia" ser reconhecida como a mesma categoria de "tecnologia"
    (e "Robotica" igual a "Robótica"), evitando filtros duplicados na landing.
    """
    base = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in base if unicodedata.category(c) != "Mn")


def evento_imagem_upload(instance, filename):
    """ Gera um caminho único baseado no título do evento e na data de upload. """
    nome_base, ext = os.path.splitext(filename)  # Obtém a extensão original
    slug = slugify(instance.title)  # Garante que o nome do arquivo seja seguro
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')  # Timestamp único
    return f"eventos/evento_{slug}_{timestamp}{ext}"  # Ex: eventos/meu-evento_20240310.jpg


def participante_foto_upload(instance, filename):
    """ Gera um caminho único para imagens de participantes. """
    nome_base, ext = os.path.splitext(filename)
    slug = slugify(instance.username)
    file_name = f"usuarios/usuario_{slug}{ext}"  
    # print(f">>> Foto do Participante: {file_name}")
    return file_name


def atividade_imagem_upload(instance, filename):
    """ Gera um caminho único para imagens de atividades. """
    nome_base, ext = os.path.splitext(filename)
    slug = slugify(instance.titulo)
    # print(f">>> Imagem da Atividade: {slug}")
    return f"eventos/atividades/atividade_{slug}{ext}"  # Ex: atividades/minha-atividade.jpg



class Participante(AbstractUser): 
    email = models.EmailField(unique=True)
    # Definir username como opcional, pois vamos preenchê-lo automaticamente
    username = models.CharField(max_length=150, unique=True, blank=True, null=True)
    USERNAME_FIELD = 'email'  # Define que o login será feito pelo e-mail
    REQUIRED_FIELDS = []  # Remove username da obrigatoriedade

    # Adicionando related_name para evitar conflitos
    groups = models.ManyToManyField(Group, related_name="participante_set", blank=True)
    user_permissions = models.ManyToManyField(Permission, related_name="participante_permissions_set", blank=True)

    foto = models.ImageField(upload_to=participante_foto_upload, blank=True, null=True)  # Diretório onde as imagens serão salvas
    # Avatar vindo do login social (Google): usado como fallback quando o
    # download do arquivo não acontece — `get_foto_url()` devolve esta URL.
    foto_social_url = models.URLField(blank=True, default="")
    bio = models.TextField(max_length=500, blank=True, null=True)

    # CPF: guardamos SOMENTE os 11 dígitos (a máscara fica na exibição).
    # NÃO é único: o e-mail é a identidade da conta e um mesmo CPF pode estar
    # ligado a mais de um e-mail.
    # `blank=False` de propósito: mantém o CPF obrigatório nos formulários do
    # organizador/perfil (que antes exigiam). O `default=""` existe só para os
    # caminhos que não perguntam o documento (login social, contas antigas).
    cpf = models.CharField(max_length=11, blank=False, default="", db_index=True)
    telefone = models.CharField(max_length=15, blank=True, null=True)
    endereco = models.TextField(blank=True, null=True)

    is_participante = models.BooleanField(default=True)
    is_organizador = models.BooleanField(default=False)
    is_palestrante = models.BooleanField(default=False)
    # Equipe de apoio: faz o check-in (câmera/código) de um evento durante a
    # sua realização, sem poder de organizador. O alcance é por evento: a conta
    # só opera nos eventos que estão no M2M `Evento.equipe`.
    is_equipe = models.BooleanField(default=False)

    objects = ParticipanteManager()

    def save(self, *args, **kwargs):
        # Normaliza o CPF em TODAS as portas de entrada (cadastro web, API,
        # admin, login social): guarda só os dígitos. Sem isso o mesmo CPF
        # entrava formatado num caminho e cru no outro.
        if self.cpf:
            self.cpf = apenas_digitos(self.cpf)

        if not self.username:  # Se o username não for preenchido, cria um baseado no email
            base_username = slugify(self.email.split('@')[0])  # Usa a parte antes do @
            new_username = base_username
            count = 1

            while Participante.objects.filter(username=new_username).exists():
                new_username = f"{base_username}{count}"
                count += 1

            self.username = new_username  # Define o novo username único

        # print(f">>> Salvando Participante: {self.username}")
        # print(f">>> Foto: {self.foto}")

        super().save(*args, **kwargs)  # Chama o método original primeiro

        if self.foto:
            img_path = self.foto.path
            img = Image.open(img_path)
                
            # Redimensiona se for muito grande
            max_size = (300, 300)  # Ajuste para o tamanho desejado
            img.thumbnail(max_size)

            # Converte para RGB se for PNG (evita erros)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            img.save(img_path, quality=85, optimize=True)  # Salva a imagem com qualidade reduzida



    def get_foto_url(self):
        if self.foto:
            return self.foto.url
        if self.foto_social_url:
            return self.foto_social_url
        return "/media/usuarios/default.jpeg"


    def __str__(self):
        return f"{self.first_name} {self.last_name}" if self.first_name else self.username


    def get_full_name(self):
        return super().get_full_name() or self.username


    class Meta:
        verbose_name = "Participante"
        verbose_name_plural = "Participantes"


    @staticmethod
    def from_user(user):
        return Participante.objects.get(pk=user.pk)


class ParticipanteMetadados(models.Model):
    """Campos extras do participante, definidos por escola (chave → valor).

    Fica numa tabela à parte de propósito: o schema de cadastro permanece
    intacto, e outra escola pode usar outros campos (turma, ano, curso…) sem
    migração. As definições vivem em `settings.METADADOS_PARTICIPANTE`.

    O campo se chama `dados` (e não `metadados`) de propósito: `participante`
    é quem tem o related_name `metadados`, então `participante.metadados.dados`
    evita `metadados.metadados`.
    """

    participante = models.OneToOneField(
        Participante, on_delete=models.CASCADE, related_name="metadados"
    )
    dados = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Metadados do participante"
        verbose_name_plural = "Metadados dos participantes"

    def __str__(self):
        return f"Metadados de {self.participante}"


class PessoaRoster(models.Model):
    """Linha da planilha (pré-carga) — serve para QUALQUER vínculo.

    Não é conta: é a fonte de dados. No primeiro login/cadastro, o e-mail é
    procurado aqui e os metadados/CPF/nome em falta são preenchidos (ver
    `eventos/roster.py`). A chave é o e-mail PESSOAL.

    O que é específico do vínculo (matrícula/curso/turma/ano para Aluno;
    função para Servidor; …) fica em `dados`, validado pelo schema
    configurável `settings.METADADOS_PARTICIPANTE` — por isso a MESMA tabela
    atende todos os vínculos.
    """

    email = models.EmailField(unique=True, db_index=True)
    nome = models.CharField(max_length=255, blank=True, default="")
    # Guardado só com os 11 dígitos (a máscara fica na exibição).
    cpf = models.CharField(max_length=11, blank=True, default="")
    # Espelho de `dados["vinculo"]`, só para filtro/relatório (indexável).
    # As opções válidas vêm de METADADOS_PARTICIPANTE (ver metadados.validar).
    vinculo = models.CharField(max_length=50, blank=True, default="", db_index=True)
    # Metadados já mapeados da planilha (vinculo/matricula/curso/turma/ano/…).
    dados = models.JSONField(default=dict, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    # -- Rastreio de uso (preenchido no 1º acesso, ver eventos/roster.py) --
    # Quando a linha foi aplicada (None = ainda não usada).
    usado_em = models.DateTimeField(null=True, blank=True)
    # True/False = o que a pessoa salvou confere com a planilha; None = não usada.
    confere = models.BooleanField(null=True, blank=True)
    # O que a pessoa efetivamente salvou no 1º acesso (nome, cpf e metadados).
    # A planilha (`dados`) NÃO é sobrescrita — assim dá para ver a divergência.
    dados_usuario = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = "Pessoa (planilha)"
        verbose_name_plural = "Pessoas (planilha)"

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        # E-mail é a chave: normaliza para minúsculas, senão o casamento com o
        # login (que o allauth normaliza) depende de maiúsculas/quebras.
        self.email = (self.email or "").strip().lower()
        if self.cpf:
            self.cpf = apenas_digitos(self.cpf)
        # Espelha o vínculo para permitir filtro/relatório no admin.
        self.vinculo = str((self.dados or {}).get("vinculo", "") or "").strip()[:50]
        super().save(*args, **kwargs)


class Evento(models.Model):
    # Vocabulário inicial de categorias. serve de sugestão no formulário e de
    # ponto de partida para a IA; não é uma restrição (o campo é texto livre).
    CATEGORIA_CHOICES = [
        ("formacao", "Formação"),
        ("ciencia", "Ciência"),
        ("tecnologia", "Tecnologia"),
        ("cultura", "Cultura"),
        ("outros", "Outros"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField()
    local = models.CharField(max_length=255)
    data_inicio = models.DateField()
    data_fim = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Tema do evento, usado na landing page para os filtros por assunto.
    # Sem `choices` de propósito: a categoria é texto livre, para o organizador
    # poder criar uma nova (a lista CATEGORIA_CHOICES é só o vocabulário
    # inicial). Categoria nova é gravada aqui e aparece sozinha nos filtros.
    categoria = models.CharField(max_length=60, default="formacao")

    imagem = models.ImageField(upload_to=evento_imagem_upload, blank=True, null=True)  # Diretório onde as imagens serão salvas

    organizador = models.ForeignKey(Participante, on_delete=models.SET_NULL, null=True, blank=True, related_name='eventos') # Quando o organizador for deletado, os eventos não serão deletados

    # Equipe de apoio do evento (check-in etc.). Fica separada do organizador:
    # cada pessoa do M2M pode operar o check-in das atividades DESTE evento,
    # sem ganhar poderes de organização.
    equipe = models.ManyToManyField(
        Participante, blank=True, related_name="eventos_equipe"
    )

    # Co-organizadores: gerenciam este evento (atividades, relatórios, edição)
    # como o dono, EXCETO excluir o evento (que é só do dono). Garante-se que
    # quem entra aqui tem is_organizador=True (o menu "Organizador" depende da
    # flag), mas o acesso aos eventos é por este vínculo.
    organizadores = models.ManyToManyField(
        Participante, blank=True, related_name="eventos_coorganizados"
    )

    # ----------------------------------------------------------------------
    # Certificados do evento
    # ----------------------------------------------------------------------
    # Carga horária padrão (horas): usada no certificado DO EVENTO e como
    # padrão das atividades que não informarem a sua.
    carga_horaria = models.PositiveIntegerField(null=True, blank=True)
    # Percentual mínimo de presença (nas atividades que emitem certificado)
    # para ter direito ao certificado DO EVENTO. Configurável pelo organizador.
    percentual_certificado = models.PositiveSmallIntegerField(default=75)

    # ----------------------------------------------------------------------
    # Modelo dos crachás DESTE evento (decisão do organizador).
    # Antes cada pessoa escolhia o seu na tela, e o evento saía com crachás de
    # dois desenhos. Agora o organizador define aqui e o participante recebe
    # exatamente esse. As chaves são as mesmas de eventos.crachas.MODELOS_CRACHA
    # (há teste travando isso).
    # ----------------------------------------------------------------------
    CRA_ETIQUETA = "etiqueta"
    CRA_CLASSICO = "classico"
    MODELO_CRACHA_CHOICES = [
        (CRA_ETIQUETA, "Etiqueta"),
        (CRA_CLASSICO, "Clássico"),
    ]
    modelo_cracha = models.CharField(
        max_length=20, choices=MODELO_CRACHA_CHOICES, default=CRA_ETIQUETA
    )

    def __str__(self):
        return self.title

    def __repr__(self):
        return f"<Evento: {self.title} [{self.data}]>"

    def get_categoria_display(self):
        """Rótulo amigável da categoria do evento.

        Mantém o mesmo nome do get_FOO_display() que o Django gerava enquanto
        o campo tinha `choices`: assim templates e API continuam funcionando
        sem alteração. Para categorias criadas depois da lista-semente, o
        rótulo é o próprio texto gravado.
        """
        return dict(self.CATEGORIA_CHOICES).get(self.categoria, self.categoria)
    
    def get_url_imagem(self):
        if self.imagem:
            return self.imagem.url
        return "/media/eventos/default.jpg"
    


    def get_n_inscricoes(self):
        """ Retorna o número total de inscrições no evento """
        return Inscricao.objects.filter(atividade__evento=self).count()
    

    def save(self, *args, **kwargs):
        """ Redimensiona e otimiza a imagem ao salvar """
        super().save(*args, **kwargs)  # Salva primeiro

        if self.imagem:
            img_path = self.imagem.path
            img = Image.open(img_path) 
            
            max_size = (1024, 768)  # Ajuste o tamanho máximo
            img.thumbnail(max_size)

            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            img.save(img_path, quality=90, optimize=True)  # Reduz qualidade    


class TipoAtividade(models.Model):
    nome = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Tipo de Atividade"
        verbose_name_plural = "Tipos de Atividades"



class Atividade(models.Model):

    evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name="atividades")
    titulo = models.CharField(max_length=255)
    descricao = models.TextField()
    # Local próprio da atividade (sala, auditório). Vazio = usa o local do evento.
    local = models.CharField(max_length=255, blank=True, default="")
    tipo = models.ForeignKey(TipoAtividade, on_delete=models.SET_NULL, null=True, blank=True, related_name="atividades") 

    palestrantes = models.ManyToManyField(Participante, related_name="atividades")

    data_hora_inicio = models.DateTimeField()
    data_hora_fim = models.DateTimeField()

    n_vagas = models.PositiveIntegerField(default=0)
    n_inscricoes = models.PositiveIntegerField(default=0)

    emite_certificado = models.BooleanField(default=False)
    # Carga horária própria da atividade (horas). Vazio = herda a do evento.
    carga_horaria = models.PositiveIntegerField(null=True, blank=True)

    # Rascunho: o organizador monta a grade sem expor ao público. Atividades
    # não publicadas ficam fora da programação, da landing, do .ics e do PDF.
    publicada = models.BooleanField(default=True)

    # ------------------------------------------------------------------
    # Proposição de atividade (chamada de propostas)
    # ------------------------------------------------------------------
    # `proponente` só existe quando a atividade nasceu de uma proposta de
    # participante; atividade criada pelo organizador fica com NULL.
    proponente = models.ForeignKey(
        Participante, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="propostas",
    )
    SITUACAO_ORGANIZADOR = "organizador"
    SITUACAO_PENDENTE = "pendente"
    SITUACAO_APROVADA = "aprovada"
    SITUACAO_REJEITADA = "rejeitada"
    SITUACAO_CHOICES = [
        (SITUACAO_ORGANIZADOR, "Criada pelo organizador"),
        (SITUACAO_PENDENTE, "Aguardando aprovação"),
        (SITUACAO_APROVADA, "Proposta aprovada"),
        (SITUACAO_REJEITADA, "Proposta rejeitada"),
    ]
    # Ciclo de vida da proposta. Serve só para separar "rascunho do
    # organizador" de "proposta de participante": quem esconde do público
    # continua sendo `publicada`.
    situacao = models.CharField(
        max_length=20, choices=SITUACAO_CHOICES,
        default=SITUACAO_ORGANIZADOR, db_index=True,
    )
    # Vaga da grade de oferta reservada por esta proposta (first-come).
    vaga = models.ForeignKey(
        "Vaga", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="propostas",
    )
    # Tipo sugerido pelo proponente quando nenhum do catálogo servia: fica como
    # texto até o organizador normalizar na aprovação (o catálogo de tipos é
    # global e único, então não é criado direto pelo proponente).
    tipo_sugerido = models.CharField(max_length=60, blank=True, default="")
    motivo_rejeicao = models.TextField(blank=True, default="")
    decidida_em = models.DateTimeField(null=True, blank=True)
    decidida_por = models.ForeignKey(
        Participante, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="propostas_decididas",
    )
    # Consentimento do proponente de que a atividade é de participação
    # voluntária e não remunerada (obrigatório no formulário de proposta).
    consentimento_voluntario = models.BooleanField(default=False)
    # Recursos, itens e equipamentos que o palestrante precisa para a atividade.
    # Não é público: serve para a organização encaminhar o que ele vai precisar.
    recursos_necessarios = models.TextField(blank=True, default="")

    @property
    def eh_proposta(self):
        """A atividade veio de uma chamada de propostas (não do organizador)?"""
        return self.situacao != self.SITUACAO_ORGANIZADOR

    @property
    def pendente(self):
        return self.situacao == self.SITUACAO_PENDENTE

    @property
    def quando_legivel(self):
        """Data e hora curtinhas para a lista: `20/09 · 19h30`.

        USE_TZ está ligado: sem localtime() a lista mostraria o horário de
        Greenwich e uma atividade das 19h30 sairia como 22h30.
        """
        def local(valor):
            if not valor:
                return None
            # Aceita data em texto: um objeto montado à mão (teste, importação,
            # API) pode chegar com a data em ISO, como já acontece no crachá.
            if isinstance(valor, str):
                try:
                    valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
                except ValueError:
                    return None
            if timezone.is_naive(valor):
                valor = timezone.make_aware(valor, timezone.get_current_timezone())
            return timezone.localtime(valor)

        inicio = local(self.data_hora_inicio)
        if not inicio:
            return ""
        fim = local(self.data_hora_fim)
        dia = inicio.strftime("%d/%m")
        if fim and fim.date() != inicio.date():
            dia = "%s a %s" % (dia, fim.strftime("%d/%m"))
        return "%s · %sh%s" % (dia, inicio.strftime("%H"), inicio.strftime("%M"))

    #campo para armazenar a confirmação da presença
    codigo_confirmacao = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)  # Código único por atividade

    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(auto_now=True) 

    imagem = models.ImageField(upload_to=atividade_imagem_upload, blank=True, null=True)  # Diretório onde as imagens serão salvas


    def vagas_disponiveis(self):
        return self.n_vagas - self.n_inscricoes
 
    def save(self, *args, **kwargs):
        """ Reescreve o método save para atualizar o número de inscrições """

        if self.pk:  # Só acessa `inscritos` se a atividade já tem um ID
            if self.n_vagas < self.n_inscricoes:
                self.n_vagas = self.n_inscricoes  # Ajusta as vagas para não serem menores que as inscrições
                
            self.n_inscricoes = self.inscritos.count()

        # print(f" Atividade>>>> Vagas: {self.n_vagas} - Inscritos: {self.n_inscricoes}")

        super().save(*args, **kwargs) # Salva primeiro

        if self.imagem:
            img_path = self.imagem.path
            img = Image.open(img_path)
            
            max_size = (600, 400)
            img.thumbnail(max_size)

            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            img.save(img_path, quality=90, optimize=True)        


    def __str__(self):
        return f"{self.titulo} - {self.evento}"
    
    def get_url_imagem(self):
        if self.imagem:
            return self.imagem.url
        return "/media/atividades/default.jpg"

    class Meta:
        verbose_name = "Atividade"
        verbose_name_plural = "Atividades"


class ChamadaProposicoes(models.Model):
    """Período em que participantes propõem atividades para um evento.

    Um por evento (OneToOne). O organizador define a janela (início/fim) e pode
    desligá-la antes do prazo com `aberta=False`. A checagem de "está aberta" é
    sempre refeita no servidor — a tela escondida não é a regra.
    """

    evento = models.OneToOneField(
        Evento, on_delete=models.CASCADE, related_name="chamada"
    )
    titulo = models.CharField(
        max_length=255, default="Chamada de propostas de atividades"
    )
    descricao = models.TextField(blank=True, default="")
    inicio = models.DateTimeField()
    fim = models.DateTimeField()
    aberta = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Chamada de proposições"
        verbose_name_plural = "Chamadas de proposições"

    def __str__(self):
        return f"Chamada de {self.evento.title}"

    def esta_aberta(self, agora=None):
        """Aberto agora? (ligado E dentro da janela.)"""
        agora = agora or timezone.now()
        return bool(self.aberta and self.inicio <= agora <= self.fim)


class Espaco(models.Model):
    """Espaço físico da escola (sala/auditório) — catálogo REAPROVEITADO.

    Não pertence a um evento: o organizador escolhe do catálogo ao montar a
    grade de vagas, e o espaço que ele cria num evento já serve para os
    próximos (é o que o evento usa que fica registrado — na `Vaga`). A
    capacidade é propriedade da sala e sugere o nº de vagas da atividade.
    """

    nome = models.CharField(max_length=160, unique=True)
    capacidade = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Espaço"
        verbose_name_plural = "Espaços"

    def __str__(self):
        return self.nome


class Vaga(models.Model):
    """Janela reservável da grade de oferta (dia + horário + espaço).

    O proponente escolhe uma vaga livre e a reserva acontece no envio da
    proposta. `capacidade` diz quantas atividades cabem na mesma janela
    (1 = exclusiva), que é o que garante "quem propõe primeiro leva".
    """

    evento = models.ForeignKey(
        Evento, on_delete=models.CASCADE, related_name="vagas"
    )
    espaco = models.ForeignKey(
        Espaco, on_delete=models.CASCADE, related_name="vagas"
    )
    inicio = models.DateTimeField()
    fim = models.DateTimeField()
    capacidade = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["espaco", "inicio", "fim"], name="unique_vaga_espaco_janela"
            )
        ]
        ordering = ["inicio", "espaco__nome"]
        verbose_name = "Vaga da chamada"
        verbose_name_plural = "Vagas da chamada"

    def __str__(self):
        return f"{self.espaco.nome} · {timezone.localtime(self.inicio):%d/%m %H:%M}"

    def propostas_ativas(self, ignorar=None):
        """Atividades que ocupam a vaga (proposta pendente/aprovada ou do organizador).

        Tudo que aponta para a vaga ocupa, menos a REJEITADA: assim a vaga volta
        a ficar livre sozinha quando o organizador recusa a proposta, e uma
        atividade que o organizador criou direto na vaga também a reserva (era
        um furo: ela não contava e a vaga seguia "livre"). `ignorar` serve à
        edição, para a própria atividade não contar como ocupante de si mesma.
        """
        ativas = self.propostas.exclude(situacao=Atividade.SITUACAO_REJEITADA)
        if getattr(ignorar, "pk", None):
            ativas = ativas.exclude(pk=ignorar.pk)
        return ativas

    @property
    def ocupadas(self):
        return self.propostas_ativas().count()

    @property
    def tem_propostas_ativas(self):
        """Há proposta pendente/aprovada nesta vaga?

        É o que trava mudar espaço/horário: a proposta copiou a janela e o
        local quando foi enviada, então mexer na vaga desmancharia a reserva.
        """
        return self.propostas_ativas().exists()

    @property
    def vagas_restantes(self):
        return max(0, self.capacidade - self.ocupadas)

    @property
    def livre(self):
        return self.vagas_restantes > 0


class Inscricao(models.Model):
    participante = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name="inscricoes")
    atividade = models.ForeignKey(Atividade, on_delete=models.CASCADE, related_name="inscritos")
    # evento = models.ForeignKey(Evento, on_delete=models.CASCADE, related_name="inscricoes")
    confirmada = models.BooleanField(default=False)
    codigo_confirmacao = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)  # Código único

    certificado_emitido = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    
    def __str__(self):
        return f"{self.participante.first_name} - {self.atividade.titulo}"

    class Meta:
        # unique_together = ('participante', 'atividade')  # Evita duplicidade

        constraints = [
            models.UniqueConstraint(fields=['participante', 'atividade'], name='unique_inscricao')
        ]        

        verbose_name = "Inscrição"
        verbose_name_plural = "Inscrições"


class Favorito(models.Model):
    """Atividade marcada como favorita por um participante ("Minha agenda").

    Fica no banco (e não só no navegador) para acompanhar a pessoa entre
    dispositivos. Anônimos seguem usando `localStorage`; ao entrar, o JS mescla
    o que estava local com o que já existe aqui.
    """

    participante = models.ForeignKey(
        Participante, on_delete=models.CASCADE, related_name="favoritos"
    )
    atividade = models.ForeignKey(
        Atividade, on_delete=models.CASCADE, related_name="favoritada_por"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["participante", "atividade"], name="unique_favorito"
            )
        ]
        verbose_name = "Favorito"
        verbose_name_plural = "Favoritos"

    def __str__(self):
        return f"{self.participante} ♥ {self.atividade}"







class Certificado(models.Model):
    """
    Model para armazenar os certificados emitidos.
    """
    participante = models.ForeignKey(Participante, on_delete=models.CASCADE, related_name="certificados")
    atividade = models.ForeignKey("Atividade", on_delete=models.SET_NULL, null=True, blank=True, related_name="certificados")
    evento = models.ForeignKey(Evento, on_delete=models.SET_NULL, null=True, blank=True, related_name="certificados_evento")
    
    codigo = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    data_emissao = models.DateTimeField(default=timezone.now)
    
    pdf = models.FileField(upload_to="usuarios/certificados/", blank=True, null=True)

    # Certificado de uma atividade ou do evento (>= percentual de presença).
    TIPO_ATIVIDADE = "atividade"
    TIPO_EVENTO = "evento"
    TIPO_CHOICES = [
        (TIPO_ATIVIDADE, "Atividade"),
        (TIPO_EVENTO, "Evento"),
    ]
    tipo = models.CharField(
        max_length=10, choices=TIPO_CHOICES, default=TIPO_ATIVIDADE, db_index=True
    )
    # Carga horária impressa no certificado (horas).
    carga_horaria = models.PositiveIntegerField(null=True, blank=True)
    # Configuração usada na emissão (rastreabilidade: qual texto/layout gerou).
    config = models.ForeignKey(
        "ConfiguracaoCertificado", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="certificados",
    )

    class Meta:
        verbose_name = "Certificado"
        verbose_name_plural = "Certificados"
        unique_together = ('participante', 'atividade', 'evento')  # Evita duplicidade

    def __str__(self):
        if self.atividade:
            return f"Certificado de {self.participante.first_name} - Atividade {self.atividade.titulo}"
        else:
            return f"Certificado de {self.participante.first_name} - Evento {self.evento.title}"


def categorias_conhecidas():
    """Pares (valor, rótulo) de todas as categorias conhecidas.

    Devolve a lista-semente na ordem canônica e, depois, as categorias criadas
    pelos organizadores em ordem alfabética. É a mesma lista que alimenta as
    sugestões do formulário (datalist) e o prompt da IA.
    """
    rotulos = dict(Evento.CATEGORIA_CHOICES)
    usadas = set(
        Evento.objects.exclude(categoria__isnull=True)
        .exclude(categoria="")
        .values_list("categoria", flat=True)
    )
    pares = list(Evento.CATEGORIA_CHOICES)
    pares += [(valor, valor) for valor in sorted(usadas - set(rotulos))]
    return pares


class Presenca(models.Model):
    """Presença de uma pessoa em uma atividade — é o que o check-in do crachá grava.

    O crachá em si não é gravado (é derivado do evento + pessoa + papel, ver
    `eventos/crachas.py`). A presença, sim: precisa de data, de quem registrou e
    de origem, porque serve de comprovação e de base para o certificado.

    Vale para os três papéis: participante tem inscrição, mas organizador e
    palestrante não — e ainda assim precisam ter presença registrada.
    """

    PAPEL_CHOICES = [
        ("organizador", "Organizador"),
        ("palestrante", "Palestrante"),
        ("participante", "Participante"),
    ]

    ORIGEM_CHOICES = [
        ("qr", "QR do crachá"),
        ("auto", "Automática (câmera da organização)"),
        ("proprio", "A própria pessoa confirmou"),
        ("codigo", "Código digitado"),
        ("manual", "Marcação manual"),
    ]

    atividade = models.ForeignKey(
        Atividade, on_delete=models.CASCADE, related_name="presencas"
    )
    participante = models.ForeignKey(
        Participante, on_delete=models.CASCADE, related_name="presencas"
    )
    # Retrato do papel no momento do registro: se a pessoa deixar de ser
    # organizadora depois, a presença de ontem continua contando como foi.
    papel = models.CharField(max_length=20, choices=PAPEL_CHOICES, default="participante")
    registrada_por = models.ForeignKey(
        Participante,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="presencas_registradas",
    )
    registrada_em = models.DateTimeField(default=timezone.now)
    origem = models.CharField(max_length=10, choices=ORIGEM_CHOICES, default="qr")

    class Meta:
        # Uma presença por pessoa por atividade: o check-in repetido não duplica,
        # apenas devolve a presença que já existe.
        constraints = [
            models.UniqueConstraint(
                fields=["atividade", "participante"], name="unique_presenca"
            )
        ]
        verbose_name = "Presença"
        verbose_name_plural = "Presenças"
        ordering = ["-registrada_em"]

    def __str__(self):
        return f"{self.participante.first_name} em {self.atividade.titulo}"

    @property
    def evento(self):
        return self.atividade.evento

    def save(self, *args, **kwargs):
        """Grava a presença e mantém `Inscricao.confirmada` em sincronia.

        A confirmação da inscrição já existia (alternada à mão no admin) e é o
        que a lista de presença e a emissão de certificado leem. Em vez de
        conviver com duas verdades sobre a mesma pessoa na mesma atividade, o
        check-in passa a marcar a inscrição correspondente.
        """
        super().save(*args, **kwargs)
        Inscricao.objects.filter(
            participante=self.participante, atividade=self.atividade
        ).update(confirmada=True)

    def delete(self, *args, **kwargs):
        """Desfazer o check-in também desmarca a inscrição.

        Atenção: se a inscrição havia sido confirmada à mão no admin e não por
        check-in, o desfazer também a desmarca — é o comportamento esperado de
        um "desfazer", mas convém saber.

        Prefira `cancelar(por=..., motivo=...)`: ele faz o mesmo e ainda deixa
        o histórico de quem desfez.
        """
        resultado = super().delete(*args, **kwargs)
        Inscricao.objects.filter(
            participante=self.participante, atividade=self.atividade
        ).update(confirmada=False)
        return resultado

    def cancelar(self, por=None, motivo=""):
        """Desfaz a presença GUARDANDO o histórico do cancelamento.

        É o caminho recomendado para desfazer um check-in: apagar direto perde
        quem desfez, quando e como era a presença — e a presença é justamente a
        comprovação que sustenta o certificado. Devolve o registro de auditoria.
        """
        registro = PresencaCancelada.objects.create(
            atividade=self.atividade,
            atividade_titulo=self.atividade.titulo if self.atividade_id else "",
            participante=self.participante,
            pessoa_nome=self.participante.get_full_name() if self.participante_id else "",
            papel=self.papel,
            origem=self.origem,
            registrada_em=self.registrada_em,
            cancelada_por=por,
            motivo=motivo,
        )
        self.delete()  # o delete() acima desmarca Inscricao.confirmada
        return registro


class PresencaCancelada(models.Model):
    """Histórico (append-only) das presenças desfeitas.

    A presença precisa poder ser desfeita — engano ao apontar a câmera, pessoa
    errada, leitura de um crachá que não era daquela atividade. Mas apagá-la sem
    deixar rastro destruiria a comprovação que ela representa. Por isso cada
    cancelamento grava uma linha aqui.

    Os nomes ficam TAMBÉM em texto (não só na FK): se a atividade ou a pessoa for
    excluída depois, o histórico continua legível. As FKs usam SET_NULL por isso.
    """

    atividade = models.ForeignKey(
        Atividade,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="presencas_canceladas",
    )
    atividade_titulo = models.CharField(max_length=255, blank=True, default="")
    participante = models.ForeignKey(
        Participante,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="presencas_canceladas",
    )
    pessoa_nome = models.CharField(max_length=255, blank=True, default="")

    # Retrato da presença no momento em que foi desfeita.
    papel = models.CharField(max_length=20, blank=True, default="")
    origem = models.CharField(max_length=10, blank=True, default="")
    registrada_em = models.DateTimeField(null=True, blank=True)

    cancelada_em = models.DateTimeField(default=timezone.now)
    cancelada_por = models.ForeignKey(
        Participante,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="presencas_canceladas_por",
    )
    motivo = models.CharField(max_length=120, blank=True, default="")

    class Meta:
        ordering = ["-cancelada_em"]
        verbose_name = "Presença cancelada"
        verbose_name_plural = "Presenças canceladas"

    def __str__(self):
        quando = self.cancelada_em.strftime("%d/%m/%Y %H:%M") if self.cancelada_em else "—"
        return f"{self.pessoa_nome or '—'} em {self.atividade_titulo or '—'} (desfeita em {quando})"


class ContextoIA(models.Model):
    """Modelo de LLM configurável por contexto (editável no admin).

    Cada ponto do sistema que chama a IA tem uma `chave` fixa, registrada em
    `eventos/ia_config.py`. Aqui o admin escolhe QUAL modelo usar em cada
    contexto, sem deploy. `modelo` vazio = usa o padrão de `settings`
    (`IA_MODELO_TEXTO`/`IA_MODELO_CLASSIFICACAO`, conforme `tipo_padrao`).

    A chave/rótulo/grupo/ordem vêm do código (comando `sincronizar_contextos_ia`);
    aqui só se edita o modelo e os ajustes.
    """

    GRUPO_GERAL = "geral"
    GRUPO_PARTICIPANTE = "participante"
    GRUPO_ORGANIZADOR = "organizador"
    GRUPO_GRAFICOS = "graficos"
    GRUPO_CHOICES = [
        (GRUPO_GERAL, "Geral"),
        (GRUPO_PARTICIPANTE, "Participante"),
        (GRUPO_ORGANIZADOR, "Organizador"),
        (GRUPO_GRAFICOS, "Gráficos"),
    ]

    TIPO_TEXTO = "texto"
    TIPO_CLASSIFICACAO = "classificacao"
    TIPO_CHOICES = [
        (TIPO_TEXTO, "Redação (texto)"),
        (TIPO_CLASSIFICACAO, "Classificação"),
    ]

    chave = models.SlugField(max_length=60, unique=True, verbose_name="Chave")
    rotulo = models.CharField(max_length=120, verbose_name="Rótulo")
    grupo = models.CharField(
        max_length=20, choices=GRUPO_CHOICES, default=GRUPO_GERAL, verbose_name="Grupo"
    )
    tipo_padrao = models.CharField(
        max_length=20, choices=TIPO_CHOICES, default=TIPO_CLASSIFICACAO,
        verbose_name="Padrão quando vazio",
        help_text="Qual padrão do ambiente usar quando o modelo não for informado.",
    )
    modelo = models.CharField(
        max_length=80, blank=True, default="", verbose_name="Modelo de LLM",
        help_text="Ex.: gpt-4o, gpt-4o-mini, gpt-5.6-luna. Vazio = padrão do ambiente.",
    )
    temperatura = models.FloatField(
        null=True, blank=True, verbose_name="Temperatura",
        help_text="Opcional. Vazio = usa o valor do código.",
    )
    max_tokens = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Máx. tokens",
        help_text="Opcional. Vazio = usa o valor do código.",
    )
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    ordem = models.PositiveIntegerField(default=0, verbose_name="Ordem")
    atualizado_em = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        ordering = ["grupo", "ordem", "rotulo"]
        verbose_name = "Contexto de IA"
        verbose_name_plural = "Contextos de IA"

    def __str__(self):
        return f"{self.rotulo} ({self.chave})"


class PalestranteSugerido(models.Model):
    """Palestrante sugerido pelo proponente que ainda não está cadastrado.

    O proponente não tem permissão para cadastrar pessoas: ele só sugere o nome
    (e contato) para que um organizador cadastre depois e vincule à atividade.
    `participante` fica NULL até a conversão.
    """

    atividade = models.ForeignKey(
        Atividade, on_delete=models.CASCADE, related_name="palestrantes_sugeridos"
    )
    nome = models.CharField(max_length=255)
    email = models.EmailField(blank=True, default="")
    telefone = models.CharField(max_length=40, blank=True, default="")
    criado_por = models.ForeignKey(
        Participante, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="palestrantes_sugeridos_criados",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    # Preenchido quando o organizador cadastra/vincula a pessoa à atividade.
    participante = models.ForeignKey(
        Participante, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="palestrantes_sugeridos_vinculados",
    )

    class Meta:
        ordering = ["criado_em", "id"]
        verbose_name = "Palestrante sugerido"
        verbose_name_plural = "Palestrantes sugeridos"

    def __str__(self):
        return "%s (proposta %s)" % (self.nome, self.atividade_id)


# ===========================================================================
# Certificados — configuração, assinaturas e catálogo de assinantes
# ===========================================================================


def assinatura_imagem_upload(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"certificados/assinaturas/assinatura_{uuid.uuid4().hex}{ext}"


def certificado_fundo_upload(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"certificados/fundos/fundo_{uuid.uuid4().hex}{ext}"


def certificado_template_upload(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"certificados/templates/template_{uuid.uuid4().hex}{ext}"


class Assinante(models.Model):
    """Assinante reutilizável do certificado (diretor, coordenação...).

    Catálogo da escola: o organizador (ou staff) cadastra uma vez e escolhe
    1–2 por evento. `imagem` é a assinatura digitalizada (opcional — sem ela,
    o certificado sai só com nome e cargo).
    """

    nome = models.CharField(max_length=150)
    cargo = models.CharField(max_length=150, blank=True, default="")
    imagem = models.ImageField(
        upload_to=assinatura_imagem_upload, blank=True, null=True
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Assinante de certificado"
        verbose_name_plural = "Assinantes de certificado"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.cargo})" if self.cargo else self.nome


class ConfiguracaoCertificado(models.Model):
    """Como um certificado é desenhado e assinado.

    Três registros possíveis por evento:
      * escopo="evento", atividade=None     -> certificado DO EVENTO;
      * escopo="atividade", atividade=None  -> PADRÃO dos certificados de atividade;
      * escopo="atividade", atividade=A     -> OVERRIDE da atividade A.

    A config efetiva de uma atividade é o override (se houver) ou o padrão de
    atividades; a do evento é a de escopo "evento". O `corpo` usa variáveis
    (`{{nome}}`, `{{tipo_atividade}}`, `{{atividade}}`, `{{evento}}`,
    `{{carga_horaria}}`, `{{data}}`, `{{local}}`, `{{qr}}`).
    """

    ESCOPO_EVENTO = "evento"
    ESCOPO_ATIVIDADE = "atividade"
    ESCOPO_CHOICES = [
        (ESCOPO_EVENTO, "Evento"),
        (ESCOPO_ATIVIDADE, "Atividade"),
    ]

    MODO_TEXTO = "texto"
    MODO_FUNDO = "fundo"
    MODO_DOCX = "docx"
    MODO_CHOICES = [
        (MODO_TEXTO, "Só texto (fundo padrão)"),
        (MODO_FUNDO, "Imagem de fundo + texto"),
        (MODO_DOCX, "Modelo .docx"),
    ]

    evento = models.ForeignKey(
        Evento, on_delete=models.CASCADE, related_name="certificado_configs"
    )
    atividade = models.OneToOneField(
        Atividade, on_delete=models.CASCADE, null=True, blank=True,
        related_name="certificado_config",
    )
    escopo = models.CharField(
        max_length=12, choices=ESCOPO_CHOICES, default=ESCOPO_EVENTO
    )
    titulo = models.CharField(max_length=150, default="CERTIFICADO")
    corpo = models.TextField(
        blank=True, default="",
        help_text="Texto do certificado. Aceita variáveis entre {{ }}.",
    )
    rodape = models.CharField(max_length=255, blank=True, default="")
    modo_layout = models.CharField(
        max_length=10, choices=MODO_CHOICES, default=MODO_TEXTO
    )
    # Modo "fundo": imagem (PNG/JPG) usada como pano de fundo.
    layout_fundo = models.ImageField(
        upload_to=certificado_fundo_upload, blank=True, null=True
    )
    # Modo "docx": template com tags {{...}} (docxtpl).
    template_docx = models.FileField(
        upload_to=certificado_template_upload, blank=True, null=True
    )
    # Carga horária padrão do certificado (vazio = usa a do evento).
    carga_horaria_padrao = models.PositiveIntegerField(null=True, blank=True)
    # Percentual mínimo de presença (sobrepõe o do evento quando preenchido).
    percentual = models.PositiveSmallIntegerField(null=True, blank=True)
    enviar_email = models.BooleanField(default=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração de certificado"
        verbose_name_plural = "Configurações de certificado"
        constraints = [
            models.UniqueConstraint(
                fields=["evento"],
                condition=models.Q(atividade__isnull=True, escopo="evento"),
                name="uniq_cert_config_evento",
            ),
            models.UniqueConstraint(
                fields=["evento"],
                condition=models.Q(atividade__isnull=True, escopo="atividade"),
                name="uniq_cert_config_atividades",
            ),
        ]

    def __str__(self):
        if self.atividade_id:
            return f"Certificado (atividade {self.atividade.titulo})"
        if self.escopo == self.ESCOPO_EVENTO:
            return f"Certificado do evento {self.evento.title}"
        return f"Certificado das atividades de {self.evento.title}"

    @property
    def percentual_efetivo(self):
        """Percentual a usar: o da config, senão o do evento."""
        return self.percentual if self.percentual is not None else self.evento.percentual_certificado


class AssinaturaCertificado(models.Model):
    """Assinatura (1 ou 2) impressa no certificado — cópia do catálogo.

    É um SNAPSHOT: guarda nome/cargo/imagem no momento da configuração, para o
    PDF continuar reproduzível mesmo que o catálogo mude depois.
    """

    config = models.ForeignKey(
        ConfiguracaoCertificado, on_delete=models.CASCADE, related_name="assinaturas"
    )
    # Assinante do catálogo que originou este snapshot (permite reabrir a seleção
    # na tela de configuração). O snapshot (nome/cargo/imagem) é o que vale.
    origem = models.ForeignKey(
        "Assinante", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    nome = models.CharField(max_length=150)
    cargo = models.CharField(max_length=150, blank=True, default="")
    imagem = models.ImageField(
        upload_to=assinatura_imagem_upload, blank=True, null=True
    )
    ordem = models.PositiveSmallIntegerField(default=1)

    class Meta:
        verbose_name = "Assinatura do certificado"
        verbose_name_plural = "Assinaturas do certificado"
        ordering = ["ordem", "id"]

    def __str__(self):
        return f"{self.ordem}. {self.nome}"
