"""Testes dos ModelAdmin: toda busca configurada precisa funcionar.

Um campo de busca que é um FK direto (ex.: `search_fields = ("participante",)`)
estoura `FieldError` no Django — o "Search" do admin daria 500. Este teste
percorre todos os admins registrados e roda a busca, pegando esse caso.
"""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone
from datetime import timedelta

from eventos.models import Participante

U = get_user_model()
SENHA = "SenhaForte123!"


class AdminSearchTests(TestCase):
    def test_toda_busca_registrada_funciona(self):
        request = RequestFactory().get("/admin/")
        for model, model_admin in admin.site._registry.items():
            with self.subTest(model=model.__name__):
                campos = model_admin.get_search_fields(request)
                if not campos:
                    continue
                queryset = model_admin.get_queryset(request)
                resultado, _dup = model_admin.get_search_results(
                    request, queryset, "teste"
                )
                list(resultado)  # avalia: lookup inválido estoura aqui

    def test_evento_e_participante_tem_busca(self):
        from eventos.models import Evento, Participante

        self.assertTrue(admin.site._registry[Evento].get_search_fields(None))
        self.assertTrue(admin.site._registry[Participante].get_search_fields(None))


class ParticipanteAdminTests(TestCase):
    """Papéis via actions, coluna de criação e datas readonly no detalhe."""

    def setUp(self):
        self.model_admin = admin.site._registry[Participante]
        self.pessoa = U.objects.create_user(
            email="adm_part@example.com", password=SENHA, cpf="11144477735"
        )

    def _alternar(self, nome):
        getattr(self.model_admin, nome)(None, Participante.objects.filter(pk=self.pessoa.pk))
        self.pessoa.refresh_from_db()

    def test_actions_alternam_os_papeis(self):
        self._alternar("alternar_equipe")
        self.assertTrue(self.pessoa.is_equipe)
        self._alternar("alternar_equipe")
        self.assertFalse(self.pessoa.is_equipe)

        self._alternar("alternar_organizador")
        self.assertTrue(self.pessoa.is_organizador)
        self._alternar("alternar_palestrante")
        self.assertTrue(self.pessoa.is_palestrante)

        # is_participante nasce True (padrão do modelo): alterna para False.
        self.assertTrue(self.pessoa.is_participante)
        self._alternar("alternar_participante")
        self.assertFalse(self.pessoa.is_participante)

    def test_action_atualiza_a_data_de_atualizacao(self):
        antigo = timezone.now() - timedelta(days=1)
        Participante.objects.filter(pk=self.pessoa.pk).update(atualizado_em=antigo)

        self._alternar("alternar_equipe")

        self.assertGreater(self.pessoa.atualizado_em, antigo)

    def test_admin_expoe_papeis_e_datas(self):
        self.assertIn("is_equipe", self.model_admin.list_display)
        self.assertIn("criado_em", self.model_admin.list_display)
        self.assertIn("date_joined", self.model_admin.readonly_fields)
        self.assertIn("last_login", self.model_admin.readonly_fields)
        self.assertIn("atualizado_em", self.model_admin.readonly_fields)


class AdminJazzminSmokeTests(TestCase):
    """O /admin/ abre com o tema (jazzmin) sem estourar template."""

    def test_admin_abre_para_superusuario(self):
        chefe = U.objects.create_superuser(
            email="adm_chefe@example.com", password=SENHA
        )
        self.client.force_login(chefe)

        resposta = self.client.get("/admin/")

        self.assertEqual(resposta.status_code, 200)


class AdminMiniaturaTests(TestCase):
    """Telas do admin com imagem mostram a miniatura (e "—" quando não há).

    Não grava arquivo: só dá um nome ao campo em memória — é o suficiente para
    `…imagem.url` montar o `<img>`, e não polui a pasta `media/` nos testes.
    """

    def test_evento(self):
        from django.utils import timezone
        from eventos.models import Evento

        evento = Evento.objects.create(
            title="E", description="d", local="l",
            data_inicio=timezone.localdate(), data_fim=timezone.localdate(),
        )
        model_admin = admin.site._registry[Evento]

        self.assertEqual(model_admin.miniatura_imagem(evento), "—")
        evento.imagem.name = "eventos/teste.png"
        html = model_admin.miniatura_imagem(evento)
        self.assertIn("<img", html)
        self.assertIn("/media/eventos/teste.png", html)
        self.assertIn("miniatura_imagem", model_admin.list_display)

    def test_atividade(self):
        from django.utils import timezone
        from eventos.models import Atividade, Evento

        evento = Evento.objects.create(
            title="E", description="d", local="l",
            data_inicio=timezone.localdate(), data_fim=timezone.localdate(),
        )
        agora = timezone.now()
        atividade = Atividade.objects.create(
            evento=evento, titulo="A", descricao="d",
            data_hora_inicio=agora, data_hora_fim=agora,
        )
        model_admin = admin.site._registry[Atividade]

        self.assertEqual(model_admin.miniatura_imagem(atividade), "—")
        atividade.imagem.name = "eventos/atividades/teste.png"
        self.assertIn("/media/eventos/atividades/teste.png", model_admin.miniatura_imagem(atividade))

    def test_assinante(self):
        from eventos.models import Assinante

        assinante = Assinante.objects.create(nome="Diretor")
        model_admin = admin.site._registry[Assinante]

        self.assertEqual(model_admin.miniatura_assinatura(assinante), "—")
        assinante.imagem.name = "certificados/assinaturas/teste.png"
        self.assertIn("/media/certificados/assinaturas/teste.png", model_admin.miniatura_assinatura(assinante))

    def test_certificado_pdf(self):
        from eventos.models import Certificado

        pessoa = U.objects.create_user(
            email="cert_adm@example.com", password=SENHA, cpf="11144477735"
        )
        certificado = Certificado.objects.create(participante=pessoa)
        model_admin = admin.site._registry[Certificado]

        self.assertEqual(model_admin.arquivo_pdf(certificado), "—")
        certificado.pdf.name = "usuarios/certificados/teste.pdf"
        html = model_admin.arquivo_pdf(certificado)
        self.assertIn("/media/usuarios/certificados/teste.pdf", html)
        self.assertIn("Abrir PDF", html)
