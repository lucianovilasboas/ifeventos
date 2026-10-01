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
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.conf import settings
from django.core import mail
from django.template.loader import render_to_string
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Atividade, Certificado, Evento, Inscricao, Presenca, PresencaCancelada, TipoAtividade
from .crachas import (
    MODELO_PADRAO,
    CrachaInvalido,
    _janela_legivel,
    arquivo_logo_cracha,
    confirmar_por_token_atividade,
    crachas_do_usuario,
    gerar_pdf_cartazes_evento,
    gerar_pdf_crachas_evento,
    gerar_token,
    gerar_token_atividade,
    gerar_token_atividade_cartaz,
    janela_de_presenca,
    ler_token_atividade,
    ler_token_atividade_cartaz,
    margens_de_presenca_atividade,
    modelo_de_cracha,
    montar_cracha,
    papel_no_evento,
    papeis_no_evento,
    pessoas_do_evento,
    url_da_logo,
)
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
            {
                "email": email, "cpf": cpf, "password1": senha, "password2": senha,
                "first_name": "Aluno", "last_name": "Teste",
                # Metadados obrigatórios (settings.METADADOS_PARTICIPANTE):
                # vínculo Aluno exige matrícula e curso.
                "meta_vinculo": "Aluno",
                "meta_matricula": "2026001", "meta_curso": "Informática",
                "meta_turma": "Turma 2", "meta_ano": "Terceiro ano",
            },
        )

    def test_salva_nome(self):
        self._cadastrar("nome@example.com", CPF_VALIDO)
        usuario = U.objects.get(email="nome@example.com")
        self.assertEqual(usuario.first_name, "Aluno")
        self.assertEqual(usuario.last_name, "Teste")

    def test_nome_obrigatorio(self):
        resposta = self.client.post(
            self.url,
            {"email": "semnome@example.com", "cpf": CPF_VALIDO,
             "password1": SENHA, "password2": SENHA,
             "meta_vinculo": "Aluno", "meta_matricula": "2026001",
             "meta_curso": "Informática"},  # falta o first_name
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("first_name", resposta.context["form"].errors)
        self.assertFalse(U.objects.filter(email="semnome@example.com").exists())

    def test_salva_metadados_do_participante(self):
        resposta = self._cadastrar("meta@example.com", CPF_VALIDO)
        self.assertEqual(resposta.status_code, 302)
        usuario = U.objects.get(email="meta@example.com")
        self.assertEqual(
            usuario.metadados.dados,
            {"vinculo": "Aluno", "matricula": "2026001", "curso": "Informática",
             "turma": "Turma 2", "ano": "Terceiro ano"},
        )

    def test_metadado_obrigatorio_e_exigido(self):
        resposta = self.client.post(
            self.url,
            {"email": "semmeta@example.com", "cpf": CPF_VALIDO,
             "password1": SENHA, "password2": SENHA, "first_name": "Aluno",
             "meta_vinculo": "Aluno",
             "meta_curso": "Informática"},  # falta a matrícula
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("meta_matricula", resposta.context["form"].errors)
        self.assertFalse(U.objects.filter(email="semmeta@example.com").exists())

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
             "password1": "SenhaForte123!", "password2": "SenhaForte123!",
             "first_name": "Aluno",
             "meta_vinculo": "Aluno",
             "meta_matricula": "2026001", "meta_curso": "Informática"},
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
            cpf="12345678909", is_organizador=True,
        )
        self.client.force_login(self.usuario)
        self.evento = Evento.objects.create(
            title="Evento de teste", description="d", local="Ponte Nova",
            data_inicio="2026-09-10", data_fim="2026-09-11",
            organizador=self.usuario,
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


class CrachasParaImpressaoTests(_BasePresencaTests):
    """Crachás para impressão: 4 por folha A4, dois modelos, PDF em lote.

    O que estes testes travam:

      * o PDF em lote sai em A4 (e não no cartão de 10 x 7 cm de antes);
      * quatro crachás por folha — a folha antiga de um por página é o que
        cortava o QR fora do papel;
      * modelo desconhecido na URL cai no padrão, nunca em erro;
      * quem não organiza o evento não baixa os crachás dos outros;
      * evento sem ninguém com papel avisa em vez de devolver PDF sem página;
      * a folha de impressão é carregada DEPOIS do cracha.css (senão a regra
        antiga de "um crachá por página" volta a valer);
      * nome comprido ganha a classe que reduz o corpo, para não sair cortado.
    """

    PAGINAS_A4 = b"/MediaBox [ 0 0 595.2756 841.8898 ]"

    def _mais_pessoas(self, quantidade):
        """Inscreve mais gente para passar de uma folha (4 por folha)."""
        for indice in range(quantidade):
            pessoa = U.objects.create_user(
                email=f"crachas{indice}@example.com", password=SENHA, cpf="12345678909",
                first_name=f"Pessoa{indice}", last_name="de Teste",
            )
            Inscricao.objects.create(participante=pessoa, atividade=self.atividade)

    def _paginas(self, dados):
        # Sem biblioteca de PDF: no arquivo, cada página tem um objeto /Type /Page
        # (o /Type /Pages é a árvore de páginas, não uma página).
        return dados.count(b"/Type /Page") - dados.count(b"/Type /Pages")

    def test_pdf_em_lote_sai_em_a4_com_quatro_por_folha(self):
        self._mais_pessoas(5)  # organizador + participante + 5 = 7 pessoas

        _, conteudo = gerar_pdf_crachas_evento(self.evento, "etiqueta")
        dados = conteudo.read()

        self.assertTrue(dados.startswith(b"%PDF"))
        self.assertIn(self.PAGINAS_A4, dados)
        # 7 pessoas / 4 por folha = 2 folhas
        self.assertEqual(self._paginas(dados), 2)

    def test_modelos_diferentes_geram_arquivos_diferentes(self):
        nome_etiqueta, etiqueta = gerar_pdf_crachas_evento(self.evento, "etiqueta")
        nome_classico, classico = gerar_pdf_crachas_evento(self.evento, "classico")

        # O modelo padrão sai sem sufixo (arquivo limpo); o outro se identifica,
        # senão os dois PDFs viram o mesmo nome na pasta de downloads.
        padrao, _ = gerar_pdf_crachas_evento(self.evento, MODELO_PADRAO)
        self.assertEqual(nome_etiqueta, padrao)
        self.assertNotEqual(nome_etiqueta, nome_classico)
        self.assertIn("classico", nome_classico)
        self.assertTrue(etiqueta.read().startswith(b"%PDF"))
        self.assertTrue(classico.read().startswith(b"%PDF"))

    def test_modelo_desconhecido_cai_no_padrao(self):
        self.assertEqual(modelo_de_cracha("inventado"), MODELO_PADRAO)
        self.assertEqual(modelo_de_cracha(None), MODELO_PADRAO)
        self.assertEqual(modelo_de_cracha("classico"), "classico")

        padrao, _ = gerar_pdf_crachas_evento(self.evento, MODELO_PADRAO)
        invalido, _ = gerar_pdf_crachas_evento(self.evento, "inventado")
        self.assertEqual(padrao, invalido)

    def test_filtro_por_papel_usa_o_principal_e_e_disjunto(self):
        """`?papel=` recorta pelo papel PRINCIPAL: cada pessoa cai em um balde só.

        Quem organiza E palestra sai como organizador (precedência), então NÃO
        aparece no recorte de palestrante — é o que evita misturar crachás.
        """
        palestrante = self._like_palestrante()
        self.atividade.palestrantes.add(self.organizador)  # organiza e palestra

        def ids(papel=None):
            return sorted(p.id for p, _ in pessoas_do_evento(self.evento, papel))

        self.assertEqual(ids("organizador"), [self.organizador.id])
        self.assertEqual(ids("palestrante"), [palestrante.id])
        self.assertEqual(ids("participante"), [self.participante.id])
        todos = sorted([self.organizador.id, self.participante.id, palestrante.id])
        self.assertEqual(ids(), todos)
        self.assertEqual(ids("todos"), todos)

    def test_pdf_filtrado_muda_o_nome_do_arquivo(self):
        self._like_palestrante()

        nome, _ = gerar_pdf_crachas_evento(self.evento, MODELO_PADRAO, "palestrante")

        self.assertIn("palestrante", nome)
        padrao, _ = gerar_pdf_crachas_evento(self.evento)
        self.assertNotEqual(nome, padrao)

    def test_organizador_baixa_o_pdf(self):
        self.client.force_login(self.organizador)

        resposta = self.client.get(
            reverse("organizador:crachas_evento", args=[self.evento.id])
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "application/pdf")
        self.assertTrue(resposta.content.startswith(b"%PDF"))

    def test_terceiro_nao_baixa_os_crachas(self):
        intruso = U.objects.create_user(
            email="intruso@example.com", password=SENHA, cpf="12345678909",
        )
        self.client.force_login(intruso)

        resposta = self.client.get(
            reverse("organizador:crachas_evento", args=[self.evento.id])
        )

        self.assertEqual(resposta.status_code, 403)

    def test_evento_sem_ninguem_avisa_em_vez_de_pdf_vazio(self):
        Inscricao.objects.all().delete()
        self.evento.organizador = None
        self.evento.save()
        self.client.force_login(self.organizador)  # não organiza mais este evento
        chefe = U.objects.create_user(
            email="chefe@example.com", password=SENHA, cpf="12345678909", is_staff=True,
        )
        self.client.force_login(chefe)

        resposta = self.client.get(
            reverse("organizador:crachas_evento", args=[self.evento.id])
        )

        self.assertEqual(resposta.status_code, 302)  # volta para a página do evento
        avisos = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertTrue(any("Ainda não há ninguém com crachá" in aviso for aviso in avisos), avisos)

    def test_api_tambem_aceita_o_modelo(self):
        self.client.force_login(self.organizador)

        resposta = self.client.get(
            reverse("crachas-evento-pdf", args=[self.evento.id]) + "?modelo=classico"
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.content.startswith(b"%PDF"))

    def test_folha_de_impressao_vem_depois_do_cracha_css(self):
        """A ordem importa: o cracha.css tem a regra antiga de um crachá por página."""
        pagina = (settings.BASE_DIR / "templates" / "participante" / "meus_crachas.html").read_text()
        posicao_cracha = pagina.index("cracha.css")
        posicao_impressao = pagina.index("cracha_impressao.css")
        self.assertLess(posicao_cracha, posicao_impressao)

        folha = (settings.BASE_DIR / "static" / "css" / "eventos" / "cracha_impressao.css").read_text()
        # A4 com 2 x 2 de 105 x 148,5 mm e a quebra de página do cracha.css desfeita
        self.assertIn("size: A4", folha)
        self.assertIn("repeat(2, 105mm)", folha)
        self.assertIn("grid-auto-rows: 148.5mm", folha)
        self.assertIn("page-break-after: auto", folha)
        self.assertIn("print-color-adjust: exact", folha)

    def test_nome_comprido_nao_sai_cortado(self):
        """Nome longo recebe a classe que reduz o corpo — a mesma régua do PDF."""
        html = render_to_string("cracha/_cracha_etiqueta.html", {
            "cracha": {
                "nome": "Maria Fernanda de Albuquerque Nascimento",
                "periodo": "12 a 14/09/2026", "papel_rotulo": "Participante",
                "codigo": "ABC-123", "qr": "data:image/png;base64,xyz",
                "evento": {"title": "Evento", "local": "Campus", "imagem": None},
            },
            "logo_url": None,
        })
        self.assertIn("etq-pessoa--longo", html)

        curto = render_to_string("cracha/_cracha_etiqueta.html", {
            "cracha": {
                "nome": "Ana Souza",
                "periodo": "12/09/2026", "papel_rotulo": "Participante",
                "codigo": "ABC-123", "qr": "data:image/png;base64,xyz",
                "evento": {"title": "Evento", "local": "Campus", "imagem": None},
            },
            "logo_url": None,
        })
        self.assertNotIn("etq-pessoa--longo", curto)
        self.assertNotIn("etq-pessoa--medio", curto)

    def test_impressao_nao_esconde_o_rodape_do_cracha(self):
        """Regressão: a regra antiga de impressão escondia TODO `<footer>`.

        O crachá clássico usa `<footer class="cracha-pe">` justamente para o
        rodapé onde vivem o QR e o código — e ele sumia no papel (a tela mostrava
        e a folha saía sem o QR). O rodapé da PÁGINA continua fora da impressão.
        """
        folha = (settings.BASE_DIR / "static" / "css" / "eventos" / "cracha_impressao.css").read_text()
        self.assertIn("footer:not(.cracha-pe)", folha)
        self.assertIn(".crachas-lista .cracha-pe", folha)

        classico = (settings.BASE_DIR / "templates" / "cracha" / "_cracha_classico.html").read_text()
        self.assertIn('<footer class="cracha-pe">', classico)
        # O rodapé tem de continuar sendo flex (a caixa do QR fica encostada à direita)
        etiqueta = (settings.BASE_DIR / "templates" / "cracha" / "_cracha_etiqueta.html").read_text()
        self.assertNotIn('class="cracha-pe"', etiqueta)  # o etiqueta usa div, não footer

    def test_botao_de_imprimir_nao_usa_classe_de_botao_so_icone(self):
        """`btn-icon` é 38x38 px FIXOS (botão só-ícone): com texto, ele sai cortado.

        Foi o que aconteceu no botão "Imprimir meus crachás" — só aparecia "meu"
        dentro de um quadradinho verde. O botão com texto usa `btn-app` (o
        primário do design system).
        """
        pagina = (settings.BASE_DIR / "templates" / "participante" / "meus_crachas.html").read_text()
        # Só a linha do botão importa: o comentário do template cita a classe
        # problemática de propósito, para explicar por que ela não está aqui.
        linha_do_botao = next(
            linha for linha in pagina.splitlines()
            if "botaoImprimir" in linha and "<button" in linha
        )
        self.assertNotIn("btn-icon", linha_do_botao)
        self.assertIn("btn-app", linha_do_botao)
        self.assertIn("Imprimir meus crachás", pagina)


class CartazesAtividadesTests(_BasePresencaTests):
    """Cartazes de QR das atividades: 1 por A4, QR permanente, só publicadas.

    O que estes testes travam:

      * o PDF sai em A4 (retrato) com UM cartaz por folha;
      * só entram atividades publicadas (rascunho não vira cartaz);
      * o QR do cartaz confirma presença e NÃO expira como o da tela;
      * fora da janela da atividade, mesmo o QR do cartaz é recusado;
      * os salts do cartaz e do QR rotativo são diferentes (um não vale no outro);
      * quem não organiza o evento não baixa os cartazes dos outros;
      * evento sem atividade publicada avisa em vez de devolver PDF vazio.
    """

    PAGINAS_A4 = b"/MediaBox [ 0 0 595.2756 841.8898 ]"

    def _mais_atividades(self, quantidade, publicada=True):
        for indice in range(quantidade):
            Atividade.objects.create(
                evento=self.evento, titulo=f"Atividade {indice}", descricao="d",
                tipo=self.tipo,
                data_hora_inicio=datetime(2026, 9, 10, 10, indice, tzinfo=timezone.utc),
                data_hora_fim=datetime(2026, 9, 10, 11, indice, tzinfo=timezone.utc),
                n_vagas=10, publicada=publicada,
            )

    def _paginas(self, dados):
        return dados.count(b"/Type /Page") - dados.count(b"/Type /Pages")

    def test_pdf_uma_folha_por_atividade(self):
        # 1 atividade -> 1 folha; com 3 -> 3 folhas (1 por folha).
        _, uma = gerar_pdf_cartazes_evento(self.evento, "etiqueta")
        self.assertEqual(self._paginas(uma.read()), 1)

        self._mais_atividades(2)
        _, tres = gerar_pdf_cartazes_evento(self.evento, "etiqueta")
        dados = tres.read()
        self.assertTrue(dados.startswith(b"%PDF"))
        self.assertIn(self.PAGINAS_A4, dados)
        self.assertEqual(self._paginas(dados), 3)

    def test_so_atividades_publicadas_entram(self):
        # 2 publicadas (2 folhas) + 1 rascunho que NÃO pode virar a 3ª folha.
        self._mais_atividades(1)
        self._mais_atividades(1, publicada=False)

        _, conteudo = gerar_pdf_cartazes_evento(self.evento, "etiqueta")

        self.assertEqual(self._paginas(conteudo.read()), 2)

    def test_token_do_cartaz_confirma_dentro_da_janela(self):
        agora = datetime.now(tz=timezone.utc)
        self.atividade.data_hora_inicio = agora - timedelta(minutes=10)
        self.atividade.data_hora_fim = agora + timedelta(hours=1)
        self.atividade.save()

        token = gerar_token_atividade_cartaz(self.atividade.id)
        atividade, presenca, criada, erro = confirmar_por_token_atividade(
            token, self.participante
        )

        self.assertEqual(erro, "")
        self.assertEqual(atividade, self.atividade)
        self.assertIsNotNone(presenca)
        self.assertTrue(criada)

    def test_token_do_cartaz_recusa_fora_da_janela(self):
        # A atividade do cenário é de 10/09/2026: a janela já fechou.
        token = gerar_token_atividade_cartaz(self.atividade.id)

        _atividade, presenca, _criada, erro = confirmar_por_token_atividade(
            token, self.participante
        )

        self.assertIsNone(presenca)
        self.assertIn("prazo", erro.lower())
        self.assertFalse(Presenca.objects.filter(atividade=self.atividade).exists())

    def test_cartaz_e_rotativo_nao_se_misturam(self):
        cartaz = gerar_token_atividade_cartaz(self.atividade.id)
        rotativo = gerar_token_atividade(self.atividade.id)

        with self.assertRaises(CrachaInvalido):
            ler_token_atividade(cartaz)
        with self.assertRaises(CrachaInvalido):
            ler_token_atividade_cartaz(rotativo)

    def test_token_invalido_nao_confirma(self):
        _atividade, presenca, _criada, erro = confirmar_por_token_atividade(
            "isto-nao-e-um-token", self.participante
        )

        self.assertIsNone(presenca)
        self.assertTrue(erro)

    def test_organizador_baixa_os_cartazes(self):
        self.client.force_login(self.organizador)

        resposta = self.client.get(
            reverse("organizador:cartazes_atividades", args=[self.evento.id])
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "application/pdf")
        self.assertTrue(resposta.content.startswith(b"%PDF"))

    def test_terceiro_nao_baixa_os_cartazes(self):
        intruso = U.objects.create_user(
            email="intruso_cartaz@example.com", password=SENHA, cpf="12345678909",
        )
        self.client.force_login(intruso)

        resposta = self.client.get(
            reverse("organizador:cartazes_atividades", args=[self.evento.id])
        )

        self.assertEqual(resposta.status_code, 403)

    def test_sem_atividades_publicadas_avisa(self):
        Atividade.objects.filter(evento=self.evento).update(publicada=False)
        self.client.force_login(self.organizador)

        resposta = self.client.get(
            reverse("organizador:cartazes_atividades", args=[self.evento.id])
        )

        self.assertEqual(resposta.status_code, 302)
        avisos = [str(m) for m in get_messages(resposta.wsgi_request)]
        self.assertTrue(
            any("Ainda não há atividades publicadas" in aviso for aviso in avisos),
            avisos,
        )

    def test_pagina_traz_o_manual_do_cartaz(self):
        """O botão "Imprimir cartazes" abre o manual; o padrão do sistema é 20/20."""
        self.client.force_login(self.organizador)

        resposta = self.client.get(
            reverse("organizador:atividades_evento", args=[self.evento.id])
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Imprimir cartazes")
        self.assertContains(resposta, "modalManualCartaz")
        # Padrão do sistema (dado real do evento) aparece no manual.
        self.assertContains(resposta, "20 min antes")
        self.assertContains(resposta, "20 min depois")
        # Link para ajustar a tolerância no próprio evento.
        self.assertContains(resposta, "Ajustar os horários de tolerância")
        self.assertContains(resposta, "folha(s) A4")

    def test_manual_usa_a_tolerancia_do_evento(self):
        """A tolerância ajustada no evento sobrepõe o padrão e aparece no manual."""
        self.evento.margem_presenca_antes_min = 5
        self.evento.margem_presenca_depois_min = 10
        self.evento.save()

        # A janela usa os valores do evento.
        abre_em, fecha_em = janela_de_presenca(self.atividade)
        self.assertEqual(abre_em, self.atividade.data_hora_inicio - timedelta(minutes=5))
        self.assertEqual(fecha_em, self.atividade.data_hora_fim + timedelta(minutes=10))

        self.client.force_login(self.organizador)
        resposta = self.client.get(
            reverse("organizador:atividades_evento", args=[self.evento.id])
        )
        self.assertContains(resposta, "5 min antes")
        self.assertContains(resposta, "10 min depois")

    def test_janela_usa_tolerancia_da_atividade(self):
        """Tolerância por atividade > do evento > padrão do sistema."""
        # Padrão do sistema quando nem atividade nem evento definem.
        self.assertEqual(margens_de_presenca_atividade(self.atividade), (20, 20))

        # Evento define: a atividade herda.
        self.evento.margem_presenca_antes_min = 15
        self.evento.margem_presenca_depois_min = 25
        self.evento.save()
        self.assertEqual(margens_de_presenca_atividade(self.atividade), (15, 25))

        # Atividade define: sobrepõe o evento.
        self.atividade.margem_presenca_antes_min = 5
        self.atividade.margem_presenca_depois_min = 8
        self.atividade.save()
        self.assertEqual(margens_de_presenca_atividade(self.atividade), (5, 8))

        abre_em, fecha_em = janela_de_presenca(self.atividade)
        self.assertEqual(abre_em, self.atividade.data_hora_inicio - timedelta(minutes=5))
        self.assertEqual(fecha_em, self.atividade.data_hora_fim + timedelta(minutes=8))

    def test_janela_legivel(self):
        """A observação impressa no cartaz: mesmo dia e virada de dia."""
        abre = datetime(2026, 9, 23, 7, 40)
        self.assertEqual(
            _janela_legivel(abre, datetime(2026, 9, 23, 9, 20)), "23/09 07:40 às 09:20"
        )
        self.assertEqual(
            _janela_legivel(abre, datetime(2026, 9, 24, 2, 20)),
            "23/09 07:40 a 24/09 02:20",
        )
        self.assertEqual(_janela_legivel(None, None), "")


class LogoDoCrachaTests(TestCase):
    """A logo do crachá tem arquivo próprio, com a antiga como reserva.

    Dois motivos: trocar a cara do crachá sem mexer no certificado (que usa
    `logo_ifmg.png`) e o crachá nunca sair sem marca se o arquivo novo faltar —
    o que acontece de verdade, porque `media/` fica fora do git e o arquivo
    precisa ser copiado em cada ambiente.
    """

    def setUp(self):
        self.media = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)

    def _escrever(self, nome):
        (self.media / nome).write_bytes(b"\x89PNG\r\n\x1a\n")

    def test_prefere_a_logo_do_cracha(self):
        self._escrever("logo_cracha.png")
        self._escrever("logo_ifmg.png")

        with override_settings(MEDIA_ROOT=self.media):
            self.assertEqual(arquivo_logo_cracha().name, "logo_cracha.png")
            self.assertEqual(url_da_logo(), "/media/logo_cracha.png")

    def test_cai_na_logo_antiga_quando_a_nova_falta(self):
        self._escrever("logo_ifmg.png")

        with override_settings(MEDIA_ROOT=self.media):
            self.assertEqual(arquivo_logo_cracha().name, "logo_ifmg.png")
            self.assertEqual(url_da_logo(), "/media/logo_ifmg.png")

    def test_sem_logo_nenhuma_o_cracha_segue_valido(self):
        with override_settings(MEDIA_ROOT=self.media):
            self.assertIsNone(arquivo_logo_cracha())
            self.assertIsNone(url_da_logo())


class PapeisNoCrachaTests(_BasePresencaTests):
    """Um crachá por evento, mostrando TODOS os papéis da pessoa nele.

    Antes, `papel_no_evento` devolvia UM papel por precedência (organizador >
    palestrante > participante) e o crachá mostrava só ele: quem organizava o
    evento e também se inscrevia numa atividade perdia a inscrição no crachá —
    e como já existia UM crachá daquele evento, não aparecia nenhum crachá de
    participante. A matriz abaixo trava cada combinação.
    """

    def _papel(self, pessoa):
        return papeis_no_evento(pessoa, self.evento)

    def _rotulos(self, pessoa):
        return montar_cracha(pessoa, self.evento)["papeis_rotulos"]

    def test_so_participante_mostra_participante(self):
        self.assertEqual(self._papel(self.participante), ["participante"])
        self.assertEqual(self._rotulos(self.participante), ["Participante"])

    def test_so_organizador_mostra_organizador(self):
        self.assertEqual(self._papel(self.organizador), ["organizador"])
        self.assertEqual(self._rotulos(self.organizador), ["Organizador"])

    def test_organizador_inscrito_mostra_OS_DOIS(self):
        """O caso relatado: ser organizador escondia a inscrição."""
        Inscricao.objects.create(participante=self.organizador, atividade=self.atividade)

        self.assertEqual(self._papel(self.organizador), ["organizador", "participante"])
        self.assertEqual(self._rotulos(self.organizador), ["Organizador", "Participante"])

    def test_palestrante_inscrito_mostra_os_dois(self):
        self.atividade.palestrantes.add(self.participante)

        self.assertEqual(self._papel(self.participante), ["palestrante", "participante"])
        self.assertEqual(self._rotulos(self.participante), ["Palestrante", "Participante"])

    def test_os_tres_papeis_na_ordem_do_mais_alto_para_o_mais_baixo(self):
        self.evento.organizador = self.participante
        self.evento.save()
        self.atividade.palestrantes.add(self.participante)

        self.assertEqual(
            self._papel(self.participante),
            ["organizador", "palestrante", "participante"],
        )
        self.assertEqual(
            self._rotulos(self.participante),
            ["Organizador", "Palestrante", "Participante"],
        )

    def test_continua_UM_cracha_por_evento(self):
        """Três papéis e duas atividades no evento: ainda é um crachá só."""
        self.evento.organizador = self.participante
        self.evento.save()
        self.atividade.palestrantes.add(self.participante)
        outra = Atividade.objects.create(
            evento=self.evento, titulo="Oficina", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc),
            data_hora_fim=datetime(2026, 9, 10, 11, 0, tzinfo=timezone.utc), n_vagas=10,
        )
        Inscricao.objects.create(participante=self.participante, atividade=outra)

        crachas = crachas_do_usuario(self.participante)
        self.assertEqual(len(crachas), 1)
        self.assertEqual(len(crachas[0]["papeis"]), 3)

    def test_sem_papel_nenhum_continua_sem_cracha(self):
        fora = U.objects.create_user(
            email="fora@example.com", password=SENHA, cpf="12345678909",
        )
        self.assertEqual(self._papel(fora), [])
        self.assertIsNone(montar_cracha(fora, self.evento))

    def test_papel_principal_continua_sendo_o_primeiro(self):
        """Presença e verificação usam um papel só: o mais alto continua sendo ele."""
        self.evento.organizador = self.participante
        self.evento.save()

        self.assertEqual(papel_no_evento(self.participante, self.evento), "organizador")

    def test_a_tela_mostra_as_duas_tarjas(self):
        """Na tela: tarja principal e a menor, com os dois papéis."""
        Inscricao.objects.create(participante=self.organizador, atividade=self.atividade)
        self.client.force_login(self.organizador)

        html = self.client.get(reverse("participante:meus_crachas")).content.decode()

        # O texto vem com a caixa normal (o CSS é que põe a tarja em maiúsculas)
        self.assertIn(">Organizador<", html)
        self.assertIn(">Participante<", html)
        self.assertIn("cracha-papel--menor", html)

    def test_a_verificacao_publica_mostra_os_mesmos_papeis(self):
        """O QR do crachá leva para uma página que conta a mesma história."""
        Inscricao.objects.create(participante=self.organizador, atividade=self.atividade)
        token = gerar_token(self.organizador.id, self.evento.id, tipo="cracha")

        html = self.client.get(reverse("verificar_cracha", args=[token])).content.decode()

        self.assertIn("Organizador", html)
        self.assertIn("Participante", html)
        self.assertIn("papel--menor", html)

    def test_o_pdf_em_lote_sai_com_os_papeis_sem_estourar(self):
        Inscricao.objects.create(participante=self.organizador, atividade=self.atividade)
        self.atividade.palestrantes.add(self.organizador)

        nome, conteudo = gerar_pdf_crachas_evento(self.evento, "etiqueta")
        dados = conteudo.read()

        self.assertTrue(dados.startswith(b"%PDF"))
        self.assertEqual(dados.count(b"/Type /Page") - dados.count(b"/Type /Pages"), 1)


class _Caneta:
    """O que o desenho devolve em beginPath()/saveState(): engole as chamadas.

    Sem isso, `recorte = c.beginPath()` recebe None e o teste quebra em
    `recorte.rect(...)` — e não no que ele quer medir.
    """

    def __getattr__(self, nome):
        return lambda *args, **kwargs: None


class _LonaFalsa:
    """Canvas falso: registra só as imagens desenhadas, para medir o QR."""

    _caneta = _Caneta()

    def __init__(self):
        self.imagens = []

    def drawImage(self, imagem, x, y, width=None, height=None, **kwargs):
        self.imagens.append((x, y, width, height))

    def stringWidth(self, texto, fonte, tamanho):
        from reportlab.pdfbase.pdfmetrics import stringWidth

        return stringWidth(texto, fonte, tamanho)

    def __getattr__(self, nome):
        return lambda *args, **kwargs: _LonaFalsa._caneta


class QrGrandeECentralizadoTests(_BasePresencaTests):
    """O QR aprovado em 13/09/2026: 34 mm, centralizado, código abaixo.

    Trava a decisão nos dois lugares: o CSS que a tela usa e a geometria que o
    PDF desenha — se um dos dois voltar atrás, o teste cai.
    """

    TAMANHO_APROVADO_MM = 34
    CENTRO_DO_CARTAO_MM = 52.5   # 105 mm de largura

    def _css(self):
        from pathlib import Path

        from django.conf import settings

        return (Path(settings.BASE_DIR) / "static/css/eventos/cracha_impressao.css").read_text(
            encoding="utf-8"
        )

    def test_css_declara_o_qr_de_34mm_nos_dois_modelos(self):
        regra = re.search(
            r"\.cracha--etiqueta \.cracha-qr,\s*\n?\.cracha--classico \.cracha-qr \{(.*?)\}",
            self._css(), re.S,
        )
        self.assertIsNotNone(regra, "a regra do QR dos dois modelos sumiu do CSS")
        self.assertIn(f"width: {self.TAMANHO_APROVADO_MM}mm", regra.group(1))
        self.assertIn(f"height: {self.TAMANHO_APROVADO_MM}mm", regra.group(1))

    def test_css_centraliza_o_rodape_nos_dois_modelos(self):
        regra = re.search(
            r"\.cracha--etiqueta \.etq-pe,\s*\n?\.cracha--classico \.cracha-pe \{(.*?)\}",
            self._css(), re.S,
        )
        self.assertIsNotNone(regra, "a regra do rodapé centralizado sumiu do CSS")
        self.assertIn("flex-direction: column", regra.group(1))
        self.assertIn("align-items: center", regra.group(1))

    def test_pdf_desenha_o_qr_de_34mm_no_centro_do_cartao(self):
        from reportlab.lib.units import mm

        from .crachas import _cracha_classico, _cracha_etiqueta

        for modelo, desenhar in (("etiqueta", _cracha_etiqueta), ("classico", _cracha_classico)):
            with self.subTest(modelo=modelo):
                lona = _LonaFalsa()
                desenhar(lona, self.participante, ["Participante"], self.evento,
                         0, 0, 105 * mm, 148.5 * mm, None)

                qrs = [i for i in lona.imagens if i[2] and abs(i[2] / mm - self.TAMANHO_APROVADO_MM) < 0.1]
                self.assertEqual(len(qrs), 1, f"{modelo}: esperava exatamente um QR de 34 mm")
                x, _y, largura, altura = qrs[0]
                self.assertAlmostEqual(largura / mm, self.TAMANHO_APROVADO_MM, places=1)
                self.assertAlmostEqual(altura / mm, self.TAMANHO_APROVADO_MM, places=1)
                self.assertAlmostEqual(
                    (x + largura / 2.0) / mm, self.CENTRO_DO_CARTAO_MM, places=1,
                    msg=f"{modelo}: o QR saiu fora do centro do cartão",
                )


class NotificacaoSocketTests(TestCase):
    """O aviso às telas usa UMA conexão por processo, não uma por evento.

    Antes: cada aviso abria conexão nova (medido: ~44 ms de handshake + ~42 ms de
    ack). Com o servidor de socket fora do ar, esse connect rodava dentro da
    requisição do usuário antes de cair no plano B em thread.
    """

    def setUp(self):
        from eventos import services

        self.services = services
        self.cliente_original = services._cliente_socket
        services._cliente_socket = None

    def tearDown(self):
        self.services._cliente_socket = self.cliente_original

    def _cliente_falso(self, falhar_no_emit=False):
        class ClienteFalso:
            def __init__(self, *args, **kwargs):
                self.connected = False
                self.conexoes = 0
                self.envios = []

            def connect(self, url, **kwargs):
                self.conexoes += 1
                self.connected = True

            def emit(self, evento, dados, **kwargs):
                if falhar_no_emit:
                    raise OSError("servidor de socket fora do ar")
                self.envios.append((evento, dados))

        return ClienteFalso

    def test_uma_conexao_para_varios_avisos(self):
        fabrica = self._cliente_falso()
        with mock.patch.object(self.services.socketio, "Client", fabrica):
            for _ in range(3):
                self.assertTrue(
                    self.services.notify_socketio("presenca_confirmada", {"atividade_id": 1})
                )
            cliente = self.services._cliente_socket

        self.assertEqual(cliente.conexoes, 1, "abriu mais de uma conexão no mesmo processo")
        self.assertEqual(len(cliente.envios), 3)
        self.assertEqual(cliente.envios[0][0], "presenca_confirmada")

    def test_falha_nao_derruba_quem_chamou_e_descarta_o_cliente(self):
        fabrica = self._cliente_falso(falhar_no_emit=True)
        with mock.patch.object(self.services.socketio, "Client", fabrica):
            self.assertFalse(self.services.notify_socketio("update_inscricao", {}))

        self.assertIsNone(self.services._cliente_socket, "devia descartar o cliente que falhou")

    def test_reconecta_depois_de_cair(self):
        fabrica = self._cliente_falso()
        with mock.patch.object(self.services.socketio, "Client", fabrica):
            self.services.notify_socketio("update_inscricao", {})
            cliente = self.services._cliente_socket
            cliente.connected = False
            self.services.notify_socketio("update_inscricao", {})

        self.assertEqual(cliente.conexoes, 2, "não reconectou depois de cair")


class AvisoDePresencaTests(_BasePresencaTests):
    """O aviso de presença leva só o sinal — nenhum dado pessoal."""

    def test_o_aviso_nao_carrega_dado_pessoal(self):
        from .crachas import notificar_presenca_confirmada

        with mock.patch("eventos.crachas.asyncio") as _asyncio_falso, \
                mock.patch("eventos.services.notify_socketio") as aviso:
            notificar_presenca_confirmada(self.atividade, presenca_id=7)

        self.assertTrue(aviso.called, "não avisou ninguém")
        evento, dados = aviso.call_args.args
        self.assertEqual(evento, "presenca_confirmada")
        self.assertEqual(
            set(dados), {"atividade_id", "evento_id", "presenca_id"},
            "o aviso passou a carregar campos além do sinal (o socket não é autenticado)",
        )
        self.assertNotIn(self.participante.email, str(dados))


class CheckinAoLocoTests(_BasePresencaTests):
    """A tela de check-in se atualiza sozinha: socket + ciclo de segurança."""

    def _html(self):
        self.client.force_login(self.organizador)
        return self.client.get(
            reverse("organizador:checkin_atividade", args=[self.atividade.id])
        ).content.decode()

    def test_a_tela_tem_socket_e_ciclo_de_seguranca(self):
        html = self._html()

        self.assertIn("socket.io.min.js", html)
        self.assertIn("const SOCKET_URL", html)
        self.assertIn("'presenca_confirmada'", html)
        self.assertIn("'presenca_cancelada'", html)
        self.assertIn("setInterval(carregarLista, INTERVALO_SEGURANCA)", html)

    def test_o_socket_nao_e_obrigatorio_para_a_lista(self):
        """O ciclo de segurança tem de existir FORA do bloco do socket."""
        html = self._html()

        trecho = html.split("setInterval(carregarLista, INTERVALO_SEGURANCA)")
        self.assertEqual(len(trecho), 2, "sumiu o ciclo de segurança da lista")


class BipeDasTelasTests(_BasePresencaTests):
    """As duas telas de credenciamento bipam, com chave de ligar/desligar.

    Três sons distintos (sucesso, aviso, erro) e a preferência no navegador —
    o som não pode começar sozinho, então a chave é obrigatória.
    """

    def _modulo(self):
        from pathlib import Path

        from django.conf import settings

        return (Path(settings.BASE_DIR) / "static/js/bipe.js").read_text(encoding="utf-8")

    def _pagina(self, rota):
        self.client.force_login(self.organizador)
        return self.client.get(reverse(rota, args=[self.atividade.id])).content.decode()

    def test_checkin_bipa_e_tem_a_chave_de_som(self):
        html = self._pagina("organizador:checkin_atividade")

        self.assertIn("js/bipe.js", html)
        self.assertIn('id="botao-som"', html)
        self.assertIn("Bipe.montarBotao", html)
        self.assertIn("Bipe.sucesso()", html)
        self.assertIn("Bipe.aviso()", html)
        self.assertIn("Bipe.erro()", html)

    def test_qrcode_bipa_e_tem_a_chave_de_som(self):
        html = self._pagina("organizador:qrcode_atividade")

        self.assertIn("js/bipe.js", html)
        self.assertIn('id="botao-som"', html)
        self.assertIn("Bipe.montarBotao", html)
        self.assertIn("Bipe.sucesso()", html)
        self.assertIn("Bipe.aviso()", html)
        # o áudio passou a ser do módulo: a tela não cria mais o contexto na mão
        self.assertNotIn("new (window.AudioContext", html)

    def test_o_modulo_tem_os_tres_sons_com_frequencias_distintas(self):
        modulo = self._modulo()

        frequencias = {}
        for som in ("sucesso", "aviso", "erro"):
            encontrado = re.search(rf"{som}: \[\[(\d+)", modulo)
            self.assertIsNotNone(encontrado, f"o som '{som}' sumiu do módulo")
            frequencias[som] = int(encontrado.group(1))

        self.assertEqual(
            len(set(frequencias.values())), 3,
            f"os três bipes precisam soar diferentes; achei {frequencias}",
        )

    def test_o_modulo_tem_os_dois_rotulos_da_chave(self):
        modulo = self._modulo()

        self.assertIn("Ligar o som", modulo)
        self.assertIn("Desligar o som", modulo)
        self.assertIn("ifeventos.som", modulo, "a preferência do som deixou de ser guardada")
        self.assertIn("localStorage", modulo)


class ModeloDoCrachaDoEventoTests(_BasePresencaTests):
    """Quem define o modelo do crachá é o organizador, no evento.

    Antes cada pessoa escolhia na tela e o mesmo evento saía com crachás de dois
    desenhos; agora o participante recebe exatamente o modelo do evento.
    """

    def test_evento_nasce_no_modelo_padrao(self):
        from .crachas import MODELO_PADRAO

        self.assertEqual(self.evento.modelo_cracha, MODELO_PADRAO)

    def test_as_chaves_do_campo_sao_as_do_gerador_de_cracha(self):
        from .crachas import MODELOS_CRACHA
        from .models import Evento

        self.assertEqual(
            {chave for chave, _ in Evento.MODELO_CRACHA_CHOICES}, set(MODELOS_CRACHA),
            "o campo do evento e o gerador de crachá precisam falar dos mesmos modelos",
        )

    def test_organizador_troca_o_modelo_do_evento(self):
        self.client.force_login(self.organizador)

        resposta = self.client.post(
            reverse("organizador:modelo_cracha_evento", args=[self.evento.id]),
            {"modelo": "classico"},
        )

        self.assertEqual(resposta.status_code, 302)
        self.evento.refresh_from_db()
        self.assertEqual(self.evento.modelo_cracha, "classico")

    def test_valor_invalido_nao_grava_lixo(self):
        self.client.force_login(self.organizador)

        self.client.post(
            reverse("organizador:modelo_cracha_evento", args=[self.evento.id]),
            {"modelo": "sei-la-o-que"},
        )

        self.evento.refresh_from_db()
        self.assertIn(self.evento.modelo_cracha, {"etiqueta", "classico"})

    def test_quem_nao_organiza_nao_troca_o_modelo(self):
        self.client.force_login(self.participante)

        resposta = self.client.post(
            reverse("organizador:modelo_cracha_evento", args=[self.evento.id]),
            {"modelo": "classico"},
        )

        self.assertEqual(resposta.status_code, 403)
        self.evento.refresh_from_db()
        self.assertNotEqual(self.evento.modelo_cracha, "classico")

    def test_o_lote_imprime_o_modelo_do_evento(self):
        self.evento.modelo_cracha = "classico"
        self.evento.save(update_fields=["modelo_cracha"])
        self.client.force_login(self.organizador)

        resposta = self.client.get(reverse("organizador:crachas_evento", args=[self.evento.id]))

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("classico", resposta.headers.get("Content-Disposition", ""))

    def test_a_tela_do_participante_mostra_so_o_modelo_do_evento(self):
        self.client.force_login(self.organizador)

        html = self.client.get(reverse("participante:meus_crachas")).content.decode()
        self.assertNotIn("crachas-modelo", html, "o seletor de modelo saiu da tela do participante")
        self.assertIn("cracha--etiqueta", html)
        self.assertNotIn("cracha--classico", html)

        self.evento.modelo_cracha = "classico"
        self.evento.save(update_fields=["modelo_cracha"])

        html = self.client.get(reverse("participante:meus_crachas")).content.decode()
        self.assertIn("cracha--classico", html)
        self.assertNotIn("cracha--etiqueta", html)


class VisualizarCrachaTests(_BasePresencaTests):
    """Crachá em tela cheia no celular, com a visão "só o QR".

    É o que permite usar o próprio celular como crachá na porta, sem imprimir.
    """

    def test_a_tela_traz_o_visualizador_e_um_botao_por_cracha(self):
        self.client.force_login(self.organizador)

        html = self.client.get(reverse("participante:meus_crachas")).content.decode()

        self.assertIn('id="crachaViewer"', html, "o visualizador tem que existir na tela")
        self.assertEqual(
            html.count("data-visualizar"), html.count("cracha-bloco"),
            "um botão de visualizar para cada crachá",
        )
        self.assertIn("Só o QR", html)
        self.assertIn("brilho", html.lower(), "a dica do brilho é o que faz o leitor pegar o QR")

    def test_o_visualizador_abre_fechado(self):
        self.client.force_login(self.organizador)

        html = self.client.get(reverse("participante:meus_crachas")).content.decode()

        trecho = html[html.index('id="crachaViewer"'):][:300]
        self.assertIn("hidden", trecho, "não pode cobrir a tela antes de ser aberto")

    def test_quem_nao_tem_cracha_nao_recebe_visualizador(self):
        from .models import Participante

        pessoa = Participante.objects.create_user(
            email="sem.cracha@exemplo.com", password=SENHA, cpf="12345678909",
        )
        self.client.force_login(pessoa)

        html = self.client.get(reverse("participante:meus_crachas")).content.decode()

        self.assertNotIn('id="crachaViewer"', html)
        self.assertIn("Você ainda não tem crachá", html)


class CertificadoEDataNaListaTests(_BasePresencaTests):
    """Botão de certificado só onde a atividade emite, e a data/hora na lista."""

    def _html_da_lista(self):
        self.client.force_login(self.organizador)
        return self.client.get(
            reverse("organizador:atividades_evento", args=[self.evento.id])
        ).content.decode()

    def test_sem_emissao_nao_tem_botao_de_certificado(self):
        self.atividade.emite_certificado = False
        self.atividade.save(update_fields=["emite_certificado"])

        html = self._html_da_lista()

        # Pelo botão renderizado, não pelo texto: "Emitir Certificados" também
        # aparece no JS que monta a linha ao vivo, e isso não é botão nenhum.
        self.assertEqual(
            html.count('data-atividade="%d"' % self.atividade.id), 0,
            "sem emissão, nenhum botão de certificado (nem no card, nem na tabela)",
        )

    def test_com_emissao_o_botao_aparece_nos_dois_layouts(self):
        self.atividade.emite_certificado = True
        self.atividade.save(update_fields=["emite_certificado"])

        html = self._html_da_lista()

        self.assertEqual(
            html.count('data-atividade="%d"' % self.atividade.id), 2,
            "um botão no card (mobile) e um na tabela (desktop)",
        )

    def test_data_e_hora_no_fuso_do_brasil(self):
        self.atividade.data_hora_inicio = datetime(2026, 9, 20, 19, 30)
        self.atividade.data_hora_fim = datetime(2026, 9, 20, 21, 0)
        self.atividade.save()

        self.assertEqual(self.atividade.quando_legivel, "20/09 · 19h30")

        self.atividade.refresh_from_db()
        self.assertEqual(
            self.atividade.quando_legivel, "20/09 · 19h30",
            "lido do banco (UTC) tem que voltar para 19h30, não 22h30",
        )

    def test_atividade_de_dois_dias_mostra_o_intervalo(self):
        self.atividade.data_hora_inicio = datetime(2026, 9, 20, 19, 30)
        self.atividade.data_hora_fim = datetime(2026, 9, 21, 12, 0)
        self.atividade.save()

        self.assertEqual(self.atividade.quando_legivel, "20/09 a 21/09 · 19h30")

    def test_a_lista_mostra_a_data_e_ordena_pelo_titulo(self):
        self.atividade.data_hora_inicio = datetime(2026, 9, 20, 19, 30)
        self.atividade.data_hora_fim = datetime(2026, 9, 20, 21, 0)
        self.atividade.save()

        html = self._html_da_lista()

        self.assertIn("20/09 · 19h30", html, "a data tem que aparecer na lista")
        valores = re.findall(r'data-valor="([^"]*)"', html)
        self.assertIn(self.atividade.titulo, valores)
        for valor in valores:
            self.assertNotIn("20/09", valor, "a data não pode entrar na ordenação")

    def test_o_payload_ao_vivo_leva_data_e_flag(self):
        capturado = {}

        def espiao(tipo, dados):
            capturado["tipo"] = tipo
            capturado["dados"] = dados

        with mock.patch("eventos.signals.notify_socketio", espiao):
            self.atividade.emite_certificado = True
            self.atividade.save()

        dados = capturado["dados"]
        self.assertTrue(dados["emite_certificado"])
        self.assertEqual(dados["quando"], self.atividade.quando_legivel)
        self.assertIn("emite_certificado", dados)


class FusoHorarioTests(TestCase):
    """Datas/horas exibidas saem no FUSO LOCAL — nunca em UTC.

    Regressão do QR do cartaz: a mensagem da janela de presença mostrava a hora
    em UTC (10:50) enquanto o cartaz dizia 07:50 (America/Sao_Paulo).
    """

    def test_local_legivel(self):
        from datetime import timezone as dt_timezone

        from django.utils import timezone as dj_timezone

        from eventos.tempo import local_legivel

        self.assertEqual(local_legivel(None), "")
        self.assertEqual(local_legivel("lixo"), "")

        naive = datetime(2026, 10, 5, 8, 0)
        esperado_naive = dj_timezone.localtime(
            dj_timezone.make_aware(naive, dj_timezone.get_current_timezone())
        ).strftime("%d/%m/%Y %H:%M")
        self.assertEqual(local_legivel(naive), esperado_naive)

        aware_utc = datetime(2026, 10, 5, 11, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(
            local_legivel(aware_utc),
            dj_timezone.localtime(aware_utc).strftime("%d/%m/%Y %H:%M"),
        )

    def test_mensagem_da_janela_no_fuso_local(self):
        from datetime import timezone as dt_timezone

        from django.utils import timezone as dj_timezone

        from eventos.crachas import atividade_aceita_presenca_agora, janela_de_presenca
        from eventos.tempo import local_legivel

        evento = Evento.objects.create(
            title="E", description="d", local="l",
            data_inicio=dj_timezone.localdate(), data_fim=dj_timezone.localdate(),
        )
        inicio = dj_timezone.make_aware(datetime(2026, 10, 5, 8, 0))
        atividade = Atividade.objects.create(
            evento=evento, titulo="A", descricao="d",
            data_hora_inicio=inicio, data_hora_fim=inicio + timedelta(hours=1),
        )
        abre_em, fecha_em = janela_de_presenca(atividade)

        _, msg_abre = atividade_aceita_presenca_agora(
            atividade, agora=abre_em - timedelta(minutes=5)
        )
        self.assertIn(local_legivel(abre_em, "%d/%m às %H:%M"), msg_abre)
        # A hora em UTC não pode aparecer (quando o fuso local difere de UTC).
        if abre_em.utcoffset() != timedelta(0):
            hora_utc = abre_em.astimezone(dt_timezone.utc).strftime("%H:%M")
            self.assertNotIn(hora_utc, msg_abre)

        _, msg_fecha = atividade_aceita_presenca_agora(
            atividade, agora=fecha_em + timedelta(minutes=5)
        )
        self.assertIn(local_legivel(fecha_em, "%d/%m às %H:%M"), msg_fecha)
