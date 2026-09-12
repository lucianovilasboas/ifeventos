"""Testes de cadastro/CPF — regressão do bug de 12/09/2026.

Contexto: o formulário de cadastro não pedia CPF e o campo era `unique=True`,
então o primeiro cadastro gravava `cpf=""` e TODOS os seguintes quebravam com
`UniqueViolation` -> HTTP 500. Estes testes travam o comportamento novo:

  * CPF é obrigatório e validado por dígito verificador;
  * CPF é gravado só com dígitos (sem máscara);
  * CPF NÃO é único: dois e-mails podem compartilhar o mesmo CPF;
  * o e-mail continua sendo a identidade única da conta.
"""

import re
from datetime import datetime, timedelta, timezone

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import Atividade, Evento, TipoAtividade
from .validators import apenas_digitos, cpf_e_valido, formatar_cpf, validar_cpf

U = get_user_model()
SENHA = "SenhaForte123!"
CPF_VALIDO = "123.456.789-09"
CPF_VALIDO_2 = "111.444.777-35"


class ValidadoresDeCpfTests(TestCase):
    """Testes unitários das funções de CPF."""

    def test_normaliza_para_digitos(self):
        self.assertEqual(apenas_digitos("123.456.789-09"), "12345678909")
        self.assertEqual(apenas_digitos(""), "")
        self.assertEqual(apenas_digitos(None), "")

    def test_formata_para_exibicao(self):
        self.assertEqual(formatar_cpf("12345678909"), "123.456.789-09")
        self.assertEqual(formatar_cpf("123.456.789-09"), "123.456.789-09")

    def test_cpf_valido(self):
        self.assertEqual(validar_cpf(CPF_VALIDO), "12345678909")
        self.assertTrue(cpf_e_valido(CPF_VALIDO_2))

    def test_cpfs_invalidos(self):
        for invalido in ("", "123", "00000000000", "11111111111", "12345678900"):
            self.assertFalse(cpf_e_valido(invalido), f"{invalido!r} deveria ser inválido")


class CadastroComCpfTests(TestCase):
    """Fluxo real da tela /accounts/signup/."""

    def setUp(self):
        self.url = reverse("account_signup")

    def _cadastrar(self, email, cpf, senha=SENHA):
        return self.client.post(
            self.url,
            {"email": email, "cpf": cpf, "password1": senha, "password2": senha},
        )

    def test_salva_cpf_sem_mascara(self):
        resposta = self._cadastrar("novo1@example.com", CPF_VALIDO)
        self.assertEqual(resposta.status_code, 302)
        usuario = U.objects.get(email="novo1@example.com")
        self.assertEqual(usuario.cpf, "12345678909")

    def test_cpf_invalido_volta_com_erro_no_campo(self):
        resposta = self._cadastrar("novo2@example.com", "111.111.111-11")
        self.assertEqual(resposta.status_code, 200)  # re-renderiza, não 500
        self.assertIn("cpf", resposta.context["form"].errors)
        self.assertFalse(U.objects.filter(email="novo2@example.com").exists())

    def test_cpf_vazio_e_rejeitado(self):
        resposta = self._cadastrar("novo3@example.com", "")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("cpf", resposta.context["form"].errors)
        self.assertFalse(U.objects.filter(email="novo3@example.com").exists())

    def test_segundo_cadastro_com_mesmo_cpf_nao_quebra(self):
        """Regressão exata do 500: dois cadastros, mesmo CPF."""
        primeira = self._cadastrar("a@example.com", CPF_VALIDO)
        self.assertEqual(primeira.status_code, 302)

        segunda = self._cadastrar("b@example.com", CPF_VALIDO)
        self.assertNotEqual(segunda.status_code, 500)
        self.assertEqual(segunda.status_code, 302)

        self.assertEqual(U.objects.filter(cpf="12345678909").count(), 2)

    def test_email_duplicado_nao_cria_segunda_conta(self):
        self._cadastrar("c@example.com", CPF_VALIDO)
        resposta = self._cadastrar("c@example.com", CPF_VALIDO_2)
        self.assertNotEqual(resposta.status_code, 500)
        self.assertEqual(U.objects.filter(email="c@example.com").count(), 1)

    def test_email_continua_sendo_a_identidade(self):
        self._cadastrar("d1@example.com", CPF_VALIDO)
        self._cadastrar("d2@example.com", CPF_VALIDO)
        self.assertEqual(U.objects.filter(cpf="12345678909").count(), 2)
        self.assertEqual(U.objects.values_list("email", flat=True).distinct().count(), 2)


class RegistroPelaApiTests(TestCase):
    """A API também deixa de bloquear CPF repetido."""

    def setUp(self):
        self.url = "/api/v1/auth/registro/"

    def _registrar(self, email, cpf):
        return self.client.post(
            self.url,
            {"email": email, "password": SENHA, "cpf": cpf},
            content_type="application/json",
        )

    def test_api_aceita_cpf_repetido(self):
        primeira = self._registrar("api1@example.com", CPF_VALIDO)
        self.assertEqual(primeira.status_code, 201)

        segunda = self._registrar("api2@example.com", CPF_VALIDO)
        self.assertEqual(segunda.status_code, 201, segunda.content)

        self.assertEqual(U.objects.filter(cpf="12345678909").count(), 2)


class ConfirmacaoDeEmailTests(TestCase):
    """Fluxo de confirmação de e-mail (allauth 65).

    Cobre dois ajustes que resolveram o relato de 12/09/2026 ("clico no link e
    ele me joga de volta para a confirmação"):
      * o e-mail deixa de vir em inglês e avisa que é preciso clicar no botão;
      * ao confirmar, o usuário já sai logado (ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION).
    """

    def setUp(self):
        self.url_signup = reverse("account_signup")
        self.url_aviso = "/accounts/confirm-email/"

    def _cadastrar(self, email="confirma@example.com"):
        return self.client.post(
            self.url_signup,
            {"email": email, "cpf": "123.456.789-09",
             "password1": "SenhaForte123!", "password2": "SenhaForte123!"},
        )

    def test_pagina_de_aviso_segue_o_padrao_visual(self):
        resposta = self.client.get(self.url_aviso)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "login-container")
        self.assertContains(resposta, "btn-app")
        self.assertContains(resposta, "Confirme seu e-mail")

    def test_post_de_cadastro_nao_loga_o_usuario(self):
        """Com verificação obrigatória, quem acabou de se cadastrar ainda não entra."""
        self._cadastrar()
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_email_de_confirmacao_vem_em_portugues(self):
        self._cadastrar()
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn("Confirme seu e-mail", msg.subject)
        self.assertNotIn("[Django]", msg.subject)
        self.assertIn("clique no botão", msg.body)
        self.assertIn("/accounts/confirm-email/", msg.body)

    def test_pagina_do_link_mostra_o_botao(self):
        self._cadastrar()
        caminho = self._caminho_do_email()
        resposta = self.client.get(caminho)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "login-container")
        self.assertContains(resposta, "Confirmar e-mail")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_confirmar_marca_verificado_e_loga_o_usuario(self):
        self._cadastrar()
        caminho = self._caminho_do_email()
        self.client.get(caminho)          # abre a página (só o GET não confirma)
        self.client.post(caminho)         # clica no botão

        endereco = EmailAddress.objects.get(email="confirma@example.com")
        self.assertTrue(endereco.verified)
        self.assertIn("_auth_user_id", self.client.session)

    def test_link_ja_usado_mostra_aviso(self):
        self._cadastrar()
        caminho = self._caminho_do_email()
        self.client.get(caminho)
        self.client.post(caminho)         # confirma
        self.client.logout()
        resposta = self.client.get(caminho)
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "já foi utilizado")

    def _caminho_do_email(self):
        corpo = mail.outbox[0].body
        url = re.search(r"https?://[^\s]+/accounts/confirm-email/\S+", corpo).group(0)
        return "/" + url.split("/", 3)[3]


class OrdenacaoDeAtividadesTests(TestCase):
    """Lista de atividades do organizador: mais inscritos no topo + colunas ordenáveis.

    A ordem padrão vem do servidor (a tabela é entregue pronta), então o teste
    olha o contexto da view — não depende de JavaScript.
    """

    def setUp(self):
        self.usuario = U.objects.create_user(
            email="organizador_teste@example.com", password="SenhaForte123!",
            cpf="12345678909",
        )
        self.client.force_login(self.usuario)
        self.evento = Evento.objects.create(
            title="Evento de teste", description="d", local="Ponte Nova",
            data_inicio="2026-09-10", data_fim="2026-09-11",
        )
        # O signal eventos.signals.atividade_salva faz `instance.tipo.nome` sem
        # checar None, então a atividade precisa de tipo (bug latente à parte).
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.url = reverse("organizador:atividades_evento", args=[self.evento.id])

    def _atividade(self, titulo, inscritos, hora):
        # Datas como datetime (não string): o signal atividade_salva chama
        # .isoformat() no valor do campo.
        inicio = datetime(2026, 9, 10, int(hora), 0, tzinfo=timezone.utc)
        return Atividade.objects.create(
            evento=self.evento, titulo=titulo, descricao="d", tipo=self.tipo,
            data_hora_inicio=inicio,
            data_hora_fim=inicio + timedelta(hours=1),
            n_vagas=100, n_inscricoes=inscritos,
        )

    def _titulos_na_ordem(self):
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 200)
        return [a.titulo for a in resposta.context["atividades"]]

    def test_mais_inscritos_vem_primeiro(self):
        self._atividade("Poucos", 1, "08")
        self._atividade("Muitos", 9, "09")
        self._atividade("Meio", 5, "10")
        self.assertEqual(self._titulos_na_ordem(), ["Muitos", "Meio", "Poucos"])

    def test_empate_desempata_por_horario(self):
        self._atividade("Mais tarde", 3, "10")
        self._atividade("Mais cedo", 3, "09")
        self.assertEqual(self._titulos_na_ordem(), ["Mais cedo", "Mais tarde"])

    def test_tabela_marcada_para_ordenacao(self):
        self._atividade("A", 1, "08")
        resposta = self.client.get(self.url)
        self.assertContains(resposta, "data-ordenavel")
        self.assertContains(resposta, 'data-sort="number"')
        self.assertContains(resposta, 'data-sort="text"')
        self.assertContains(resposta, 'data-renumerar')
        self.assertContains(resposta, "tabela_ordenavel.js")

    def test_coluna_de_acoes_nao_ordena(self):
        self._atividade("A", 1, "08")
        html = self.client.get(self.url).content.decode()
        cabecalho = html.split("<thead")[1].split("</thead>")[0]
        self.assertIn("Ações", cabecalho)
        self.assertNotIn('data-sort="text">Ações', cabecalho)


class AtividadeSemTipoNemDatetimeTests(TestCase):
    """Regressão do signal atividade_salva.

    Ele fazia `instance.tipo.nome` e `instance.data_hora_inicio.isoformat()`
    direto. Como `tipo` é opcional no model (e não obrigatório na API), criar
    atividade sem tipo derrubava a requisição com AttributeError -> 500.
    """

    def setUp(self):
        self.evento = Evento.objects.create(
            title="Evento", description="d", local="l",
            data_inicio="2026-09-10", data_fim="2026-09-11",
        )

    def test_atividade_sem_tipo_nao_estoura(self):
        atividade = Atividade.objects.create(
            evento=self.evento, titulo="Sem tipo", descricao="d", tipo=None,
            data_hora_inicio=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc),
            data_hora_fim=datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc),
            n_vagas=10,
        )
        self.assertIsNotNone(atividade.pk)
        self.assertIsNone(atividade.tipo)

    def test_atividade_com_data_em_string_nao_estoura(self):
        atividade = Atividade.objects.create(
            evento=self.evento, titulo="Data em string", descricao="d",
            data_hora_inicio="2026-09-10T08:00:00-03:00",
            data_hora_fim="2026-09-10T09:00:00-03:00",
            n_vagas=10,
        )
        self.assertIsNotNone(atividade.pk)

    def test_edicao_de_atividade_sem_tipo_nao_estoura(self):
        atividade = Atividade.objects.create(
            evento=self.evento, titulo="Sem tipo", descricao="d", tipo=None,
            data_hora_inicio=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc),
            data_hora_fim=datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc),
            n_vagas=10,
        )
        atividade.n_vagas = 20          # segunda gravação (created=False)
        atividade.save()
        self.assertEqual(Atividade.objects.get(pk=atividade.pk).n_vagas, 20)
