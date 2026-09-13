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
    tipo = models.ForeignKey(TipoAtividade, on_delete=models.SET_NULL, null=True, blank=True, related_name="atividades") 

    palestrantes = models.ManyToManyField(Participante, related_name="atividades")

    data_hora_inicio = models.DateTimeField()
    data_hora_fim = models.DateTimeField()

    n_vagas = models.PositiveIntegerField(default=0)
    n_inscricoes = models.PositiveIntegerField(default=0)

    emite_certificado = models.BooleanField(default=False)

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
