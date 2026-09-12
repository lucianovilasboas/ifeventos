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

from .models import Atividade, Certificado, Evento, Inscricao, Presenca, PresencaCancelada, TipoAtividade
from .inscricoes import InscricaoBloqueada, cancelar_inscricao
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


class _BasePresencaTests(TestCase):
    """Cenário comum: um evento, uma atividade, um participante inscrito.

    Não tem teste nenhum de propósito — é a base compartilhada entre os testes
    de regra (presença/inscrição) e os de interface (API e tela do QR). Assim os
    dois rodam o MESMO cenário sem repetir os testes um do outro.
    """

    def setUp(self):
        self.evento = Evento.objects.create(
            title="Evento de teste", description="d", local="Ponte Nova",
            data_inicio="2026-09-10", data_fim="2026-09-11",
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Abertura", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc),
            data_hora_fim=datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc),
            n_vagas=50,
        )
        self.participante = U.objects.create_user(
            email="participante_teste@example.com", password=SENHA, cpf="12345678909",
        )
        self.organizador = U.objects.create_user(
            email="organizador_teste@example.com", password=SENHA, cpf="11144477735",
        )
        # "Organizador" de verdade é quem está no evento (ou tem a flag/staff):
        # ser um usuário comum não dá poder sobre o check-in.
        self.evento.organizador = self.organizador
        self.evento.save()
        self.inscricao = Inscricao.objects.create(
            participante=self.participante, atividade=self.atividade, confirmada=True,
        )

    def _presenca(self, participante=None):
        # Uma presença por pessoa por atividade (unique_presenca).
        return Presenca.objects.create(
            atividade=self.atividade,
            participante=participante or self.participante,
            papel="participante", origem="qr", registrada_por=self.organizador,
        )

    def _like_palestrante(self, email="palestrante_teste@example.com"):
        """Quem palestra NA atividade: abre o QR, mas não gerencia o evento."""
        palestrante = U.objects.create_user(
            email=email, password=SENHA, cpf="12345678909",
        )
        self.atividade.palestrantes.add(palestrante)
        return palestrante


class PresencaCanceladaTests(_BasePresencaTests):
    """Desfazer presença deixa histórico; sair da inscrição leva a presença junto.

    O que estes testes travam:

      * desfazer grava QUEM desfez, QUANDO e como era a presença;
      * desfazer volta `Inscricao.confirmada` para False;
      * remover a inscrição remove a presença daquela atividade;
      * com certificado já emitido a remoção é RECUSADA — apagar a presença
        deixaria o certificado sem nenhuma comprovação por trás;
      * a rede de segurança cobre a remoção em lote (`queryset.delete()`), que
        não passa pelo serviço.
    """

    # --- o cancelamento em si ------------------------------------------------

    def test_desfazer_presenca_grava_auditoria(self):
        presenca = self._presenca()

        presenca.cancelar(por=self.organizador, motivo="Engano na leitura")

        self.assertFalse(Presenca.objects.filter(pk=presenca.pk).exists())
        auditoria = PresencaCancelada.objects.get()
        self.assertEqual(auditoria.cancelada_por, self.organizador)
        self.assertEqual(auditoria.motivo, "Engano na leitura")
        # Retrato do que foi desfeito: como era, de quem era, onde.
        self.assertEqual(auditoria.atividade_titulo, "Abertura")
        self.assertEqual(auditoria.papel, "participante")
        self.assertEqual(auditoria.origem, "qr")
        self.assertTrue(auditoria.pessoa_nome)
        self.assertIsNotNone(auditoria.registrada_em)
        self.assertIsNotNone(auditoria.cancelada_em)

    def test_desfazer_desmarca_inscricao_confirmada(self):
        presenca = self._presenca()
        self.assertTrue(self.inscricao.confirmada)

        presenca.cancelar(por=self.organizador)

        self.inscricao.refresh_from_db()
        self.assertFalse(self.inscricao.confirmada)

    def test_auditoria_sobrevive_a_exclusao_da_atividade(self):
        """A história do cancelamento não pode depender de quem foi apagado."""
        presenca = self._presenca()
        presenca.cancelar(por=self.organizador, motivo="Engano")

        self.atividade.delete()

        auditoria = PresencaCancelada.objects.get()
        self.assertIsNone(auditoria.atividade)
        self.assertEqual(auditoria.atividade_titulo, "Abertura")  # texto preservado
        self.assertTrue(auditoria.pessoa_nome)

    # --- remoção de inscrição leva a presença --------------------------------

    def test_remover_inscricao_remove_presenca_da_atividade(self):
        presenca = self._presenca()

        cancelar_inscricao(self.inscricao, por=self.participante)

        self.assertFalse(Inscricao.objects.filter(pk=self.inscricao.pk).exists())
        self.assertFalse(Presenca.objects.filter(pk=presenca.pk).exists())
        auditoria = PresencaCancelada.objects.get()
        self.assertEqual(auditoria.motivo, "Cancelamento de inscrição")
        self.assertEqual(auditoria.cancelada_por, self.participante)

    def test_rede_de_seguranca_cobre_remocao_em_lote(self):
        """`queryset.delete()` (admin, lote) não passa pelo serviço."""
        presenca = self._presenca()

        Inscricao.objects.filter(pk=self.inscricao.pk).delete()

        self.assertFalse(Presenca.objects.filter(pk=presenca.pk).exists())
        # A rede de segurança limpa estado; auditoria é para ação de gente, e
        # ninguém desfez nada aqui — quem removeu a inscrição em lote não passa
        # por `cancelar_inscricao`.
        self.assertEqual(PresencaCancelada.objects.count(), 0)

    def test_excluir_atividade_com_inscricao_e_presenca_nao_estoura(self):
        """Regressão: a cascata não pode tentar auditar o que está sendo apagado.

        Excluir a atividade apaga inscrição e presença em cascata. Se a rede de
        segurança gravasse auditoria nesse instante, ela apontaria para a
        atividade já removida e a exclusão morria com violação de chave
        estrangeira (visto na verificação no app real).
        """
        self._presenca()

        self.atividade.delete()

        self.assertFalse(Presenca.objects.exists())
        self.assertFalse(Inscricao.objects.exists())

    def test_excluir_evento_com_inscricao_e_presenca_nao_estoura(self):
        """Mesmo caminho, um nível acima: excluir o evento inteiro."""
        self._presenca()

        self.evento.delete()

        self.assertFalse(Presenca.objects.exists())
        self.assertFalse(Inscricao.objects.exists())

    def test_excluir_pessoa_com_inscricao_e_presenca_nao_estoura(self):
        """E excluir a pessoa: a presença vai junto, sem tentar auditar."""
        self._presenca()

        U.objects.filter(pk=self.participante.pk).delete()

        self.assertFalse(Presenca.objects.exists())

    def test_remover_inscricao_sem_presenca_nao_estoura(self):
        """Quem nunca confirmou presença também pode sair da inscrição."""
        cancelar_inscricao(self.inscricao, por=self.participante)

        self.assertFalse(Inscricao.objects.filter(pk=self.inscricao.pk).exists())
        self.assertEqual(PresencaCancelada.objects.count(), 0)

    # --- a trava do certificado ----------------------------------------------

    def test_recusa_quando_ha_certificado_da_atividade(self):
        self._presenca()
        Certificado.objects.create(
            participante=self.participante, atividade=self.atividade, evento=self.evento,
        )

        with self.assertRaises(InscricaoBloqueada):
            cancelar_inscricao(self.inscricao, por=self.participante)

        # Nada mudou: nem inscrição, nem presença, nem auditoria.
        self.assertTrue(Inscricao.objects.filter(pk=self.inscricao.pk).exists())
        self.assertTrue(
            Presenca.objects.filter(
                participante=self.participante, atividade=self.atividade
            ).exists()
        )
        self.assertEqual(PresencaCancelada.objects.count(), 0)

    def test_recusa_quando_ha_certificado_do_evento(self):
        """O certificado de EVENTO é emitido contando atividades confirmadas."""
        self._presenca()
        Certificado.objects.create(
            participante=self.participante, atividade=None, evento=self.evento,
        )

        with self.assertRaises(InscricaoBloqueada):
            cancelar_inscricao(self.inscricao, por=self.participante)

        self.assertTrue(Inscricao.objects.filter(pk=self.inscricao.pk).exists())

    def test_certificado_de_outra_pessoa_nao_bloqueia(self):
        outro = U.objects.create_user(
            email="outro_teste@example.com", password=SENHA, cpf="11144477735",
        )
        Certificado.objects.create(
            participante=outro, atividade=self.atividade, evento=self.evento,
        )
        self._presenca()

        cancelar_inscricao(self.inscricao, por=self.participante)

        self.assertFalse(Inscricao.objects.filter(pk=self.inscricao.pk).exists())


class DesfazerPresencaPelaApiTests(_BasePresencaTests):
    """O caminho da API (o mesmo que o MCP usa) e o da tela do QR."""

    def test_api_cancelar_inscricao_remove_presenca(self):
        presenca = self._presenca()
        self.client.force_login(self.participante)

        resposta = self.client.delete(
            reverse("minha-inscricao-detail", args=[self.inscricao.id])
        )

        self.assertEqual(resposta.status_code, 204)
        self.assertFalse(Presenca.objects.filter(pk=presenca.pk).exists())
        self.assertFalse(Inscricao.objects.filter(pk=self.inscricao.pk).exists())

    def test_api_recusa_com_certificado_e_explica_por_que(self):
        self._presenca()
        Certificado.objects.create(
            participante=self.participante, atividade=self.atividade, evento=self.evento,
        )
        self.client.force_login(self.participante)

        resposta = self.client.delete(
            reverse("minha-inscricao-detail", args=[self.inscricao.id])
        )

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("certificado", resposta.json()["detail"].lower())
        self.assertTrue(Inscricao.objects.filter(pk=self.inscricao.pk).exists())

    def test_api_desfazer_presenca_grava_auditoria(self):
        """O DELETE da presença (o do ✕ na tela) não apaga sem deixar rastro."""
        presenca = self._presenca()
        self.client.force_login(self.organizador)

        resposta = self.client.delete(reverse("presenca-detail", args=[presenca.id]))

        self.assertIn(resposta.status_code, (204, 200))
        self.assertFalse(Presenca.objects.filter(pk=presenca.pk).exists())
        auditoria = PresencaCancelada.objects.get()
        self.assertEqual(auditoria.cancelada_por, self.organizador)

    def test_organizador_ve_o_x_na_tela_do_qr(self):
        self._presenca()
        self.client.force_login(self.organizador)

        resposta = self.client.get(
            reverse("organizador:qrcode_atividade", args=[self.atividade.id])
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "PODE_DESFAZER = true")

    def test_palestrante_nao_ve_o_x_mas_ve_a_lista(self):
        """Palestrante mostra o QR, mas desfazer presença é de quem organiza.

        Sem essa separação ele veria um ✕ que sempre falha com 403.
        """
        palestrante = self._like_palestrante()
        self._presenca()
        self.client.force_login(palestrante)

        resposta = self.client.get(
            reverse("organizador:qrcode_atividade", args=[self.atividade.id])
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "PODE_DESFAZER = false")

    def test_palestrante_recebe_403_ao_tentar_desfazer(self):
        """A tela esconde o ✕, e a API recusa — as duas pontas concordam."""
        palestrante = self._like_palestrante("palestrante2_teste@example.com")
        presenca = self._presenca()
        self.client.force_login(palestrante)

        resposta = self.client.delete(reverse("presenca-detail", args=[presenca.id]))

        self.assertIn(resposta.status_code, (403, 404))
        self.assertTrue(Presenca.objects.filter(pk=presenca.pk).exists())
