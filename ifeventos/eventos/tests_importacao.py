"""Testes da importação de metadados por CSV (eventos/importacao.py)."""

import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from eventos import importacao

U = get_user_model()
SENHA = "SenhaForte123!"


def _arquivo(texto):
    return io.StringIO(texto)


class ImportacaoMetadadosTests(TestCase):
    def setUp(self):
        self.aluno = U.objects.create_user(
            email="aluno@example.com", password=SENHA, cpf="12345678909"
        )

    def _importar(self, texto):
        return importacao.importar(_arquivo(texto))

    def _dados(self, usuario=None):
        usuario = usuario or self.aluno
        usuario.refresh_from_db()
        return usuario.metadados.dados

    def test_atualiza_participante_existente(self):
        relatorio = self._importar(
            "email,vinculo,matricula,curso,ano\n"
            "aluno@example.com,Aluno,2026001,TPG,Primeiro período\n"
        )
        self.assertEqual(relatorio["atualizados"], 1)
        self.assertEqual(relatorio["erros"], 0)
        self.assertEqual(
            self._dados(),
            {"vinculo": "Aluno", "matricula": "2026001", "curso": "TPG",
             "ano": "Primeiro período"},
        )

    def test_celula_vazia_mantem_o_valor(self):
        self._importar("email,vinculo,matricula,curso,ano\n"
                       "aluno@example.com,Aluno,2026001,TPG,Primeiro período\n")
        # Segunda importação só troca a turma; o resto fica.
        relatorio = self._importar("email,vinculo,matricula,curso,turma\n"
                                   "aluno@example.com,Aluno,2026001,TPG,Turma 2\n")
        self.assertEqual(relatorio["atualizados"], 1)
        dados = self._dados()
        self.assertEqual(dados["turma"], "Turma 2")
        self.assertEqual(dados["ano"], "Primeiro período")  # preservado

    def test_email_inexistente_e_erro(self):
        relatorio = self._importar("email,vinculo\nninguem@example.com,Aluno\n")
        self.assertEqual(relatorio["erros"], 1)
        self.assertEqual(relatorio["linhas"][0]["status"], "erro")

    def test_campo_que_nao_se_aplica_e_ignorado_com_aviso(self):
        relatorio = self._importar(
            "email,vinculo,funcao,matricula\n"
            "aluno@example.com,Servidor,Professor,2026001\n"
        )
        self.assertEqual(relatorio["atualizados"], 1)
        item = relatorio["linhas"][0]
        self.assertTrue(any("Matrícula" in a for a in item["avisos"]))
        dados = self._dados()
        self.assertEqual(dados, {"vinculo": "Servidor", "funcao": "Professor"})
        self.assertNotIn("matricula", dados)

    def test_obrigatorio_ausente_e_erro(self):
        relatorio = self._importar(
            "email,vinculo,curso\naluno@example.com,Aluno,Informática\n"
        )
        self.assertEqual(relatorio["erros"], 1)
        self.assertTrue(any("Matrícula" in e for e in relatorio["linhas"][0]["erros"]))
        self.assertFalse(hasattr(self.aluno, "metadados"))

    def test_opcao_invalida_e_erro(self):
        relatorio = self._importar(
            "email,vinculo,matricula,curso\n"
            "aluno@example.com,Aluno,1,CursoQueNaoExiste\n"
        )
        self.assertEqual(relatorio["erros"], 1)
        self.assertTrue(any("Curso" in e for e in relatorio["linhas"][0]["erros"]))

    def test_dependencia_invalida_e_erro(self):
        relatorio = self._importar(
            "email,vinculo,matricula,curso,ano\n"
            "aluno@example.com,Aluno,1,TPG,Primeiro ano\n"
        )
        self.assertEqual(relatorio["erros"], 1)
        self.assertTrue(any("Ano" in e for e in relatorio["linhas"][0]["erros"]))

    def test_sem_coluna_email_e_erro_geral(self):
        relatorio = self._importar("vinculo,matricula\nAluno,1\n")
        self.assertIn("erro_geral", relatorio)

    def test_aceita_ponto_e_virgula(self):
        relatorio = self._importar(
            "email;vinculo;matricula;curso\n"
            "aluno@example.com;Aluno;1;Informática\n"
        )
        self.assertEqual(relatorio["atualizados"], 1)
        self.assertEqual(self._dados()["curso"], "Informática")


class ImportacaoViewTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org_imp@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.participante = U.objects.create_user(
            email="aluno@example.com", password=SENHA, cpf="11144477735"
        )
        self.url = reverse("organizador:importar_metadados")

    def test_modelo_csv_tem_os_cabecalhos(self):
        self.client.force_login(self.org)
        resposta = self.client.get(reverse("organizador:modelo_metadados_csv"))
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("text/csv", resposta["Content-Type"])
        primeira = resposta.content.decode("utf-8-sig").splitlines()[0]
        self.assertEqual(
            primeira.split(","),
            ["email", "vinculo", "matricula", "curso", "turma", "ano", "funcao"],
        )

    def test_organizador_importa_pela_view(self):
        self.client.force_login(self.org)
        arquivo = SimpleUploadedFile(
            "m.csv",
            b"email,vinculo,matricula,curso\naluno@example.com,Aluno,1,Inform\xc3\xa1tica\n",
            content_type="text/csv",
        )
        resposta = self.client.post(self.url, {"arquivo": arquivo})
        self.assertEqual(resposta.status_code, 200)
        self.participante.refresh_from_db()
        self.assertEqual(self.participante.metadados.dados["curso"], "Informática")

    def test_participante_nao_pode_importar(self):
        self.client.force_login(self.participante)
        resposta = self.client.get(self.url)
        self.assertEqual(resposta.status_code, 302)
