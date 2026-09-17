"""Testes dos metadados configuráveis do participante."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.http import QueryDict
from django.test import TestCase, override_settings
from django.urls import reverse

from eventos import metadados
from eventos.models import PessoaRoster

U = get_user_model()
SENHA = "SenhaForte123!"
CPF = "123.456.789-09"

CONFIG = [
    {"chave": "matricula", "rotulo": "Matrícula", "tipo": "texto", "obrigatorio": True, "ordem": 1},
    {"chave": "turma", "rotulo": "Turma", "tipo": "escolha", "opcoes": ["A", "B"], "ordem": 2},
]


class CamposMetadadosTests(TestCase):
    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_campos_normalizados_e_ordenados(self):
        campos = metadados.campos()
        self.assertEqual([c["chave"] for c in campos], ["matricula", "turma"])
        self.assertTrue(campos[0]["obrigatorio"])
        self.assertEqual(campos[1]["tipo"], "escolha")
        self.assertEqual(campos[1]["opcoes"], ["A", "B"])

    @override_settings(METADADOS_PARTICIPANTE=[])
    def test_config_vazia(self):
        self.assertEqual(metadados.campos(), [])

    @override_settings(METADADOS_PARTICIPANTE=[{"chave": "", "rotulo": "x"}])
    def test_item_sem_chave_e_ignorado(self):
        self.assertEqual(metadados.campos(), [])

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_field_de_escolha_tem_choices(self):
        campo = metadados.construir_field(metadados.campos()[1])
        self.assertEqual(campo.choices, [("", "Selecione…"), ("A", "A"), ("B", "B")])

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_colunas_selecionadas(self):
        todas = metadados.colunas_selecionadas(QueryDict(""))
        self.assertEqual([c["chave"] for c in todas], ["matricula", "turma"])

        uma = metadados.colunas_selecionadas(QueryDict("campos=matricula"))
        self.assertEqual([c["chave"] for c in uma], ["matricula"])

        nenhuma = metadados.colunas_selecionadas(QueryDict("campos="))
        self.assertEqual(nenhuma, [])

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_coletar_so_chaves_configuradas(self):
        coletado = metadados.coletar(
            {"meta_matricula": "1", "meta_turma": "B", "meta_lixo": "x"}
        )
        self.assertEqual(coletado, {"matricula": "1", "turma": "B"})


class CadastroCondicionalTests(TestCase):
    """O vínculo condiciona os campos; o curso condiciona o ano/período."""

    def setUp(self):
        self.url = reverse("account_signup")

    def _post(self, **extra):
        dados = {"email": "cond@example.com", "cpf": CPF, "password1": SENHA,
                 "password2": SENHA, "first_name": "Aluno"}
        dados.update(extra)
        return self.client.post(self.url, dados)

    def _dados(self):
        return U.objects.get(email="cond@example.com").metadados.dados

    def test_aluno_valido(self):
        r = self._post(meta_vinculo="Aluno", meta_matricula="1",
                       meta_curso="TPG", meta_ano="Primeiro período")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            self._dados(),
            {"vinculo": "Aluno", "matricula": "1", "curso": "TPG",
             "ano": "Primeiro período"},
        )

    def test_aluno_sem_matricula_e_erro(self):
        r = self._post(meta_vinculo="Aluno", meta_curso="Informática")
        self.assertEqual(r.status_code, 200)
        self.assertIn("meta_matricula", r.context["form"].errors)

    def test_ano_incompativel_com_o_curso_e_erro(self):
        r = self._post(meta_vinculo="Aluno", meta_matricula="1",
                       meta_curso="TPG", meta_ano="Primeiro ano")
        self.assertEqual(r.status_code, 200)
        self.assertIn("meta_ano", r.context["form"].errors)

    def test_servidor_exige_funcao(self):
        r = self._post(meta_vinculo="Servidor")
        self.assertEqual(r.status_code, 200)
        self.assertIn("meta_funcao", r.context["form"].errors)

    def test_servidor_com_funcao(self):
        r = self._post(meta_vinculo="Servidor", meta_funcao="Professor")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._dados(), {"vinculo": "Servidor", "funcao": "Professor"})

    def test_comunidade_externa_so_exige_vinculo(self):
        r = self._post(meta_vinculo="Comunidade externa")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._dados(), {"vinculo": "Comunidade externa"})

    def test_colaborador_nao_exige_mais_nada(self):
        r = self._post(meta_vinculo="Colaborador")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self._dados(), {"vinculo": "Colaborador"})


class ColetarVisibilidadeTests(TestCase):
    """O que não está visível não é gravado."""

    def test_descarta_campos_ocultos(self):
        dados = metadados.coletar({
            "meta_vinculo": "Comunidade externa",
            "meta_matricula": "1", "meta_curso": "TPG", "meta_ano": "Primeiro período",
        })
        self.assertEqual(dados, {"vinculo": "Comunidade externa"})

    def test_mantem_os_visiveis(self):
        dados = metadados.coletar({
            "meta_vinculo": "Servidor", "meta_funcao": "Professor",
        })
        self.assertEqual(dados, {"vinculo": "Servidor", "funcao": "Professor"})


class LimparMetadadoCommandTests(TestCase):
    """O comando apaga a chave dos três lugares onde o valor pode ficar."""

    def setUp(self):
        self.usuario = U.objects.create_user(
            email="limpa@example.com", password=SENHA, cpf="11144477735"
        )
        metadados.salvar(self.usuario, {
            "vinculo": "Servidor", "funcao": "Professor", "siape": "123",
        })
        self.linha = PessoaRoster.objects.create(
            email="limpa@example.com",
            dados={"vinculo": "Servidor", "funcao": "Professor", "siape": "123"},
            dados_usuario={
                "nome": "Limpa Teste", "cpf": "",
                "metadados": {"funcao": "Professor", "siape": "123"},
            },
        )

    def test_dry_run_nao_altera_nada(self):
        call_command("limpar_metadado", "siape", stdout=StringIO())

        self.assertEqual(metadados.dados_de(self.usuario).get("siape"), "123")
        self.linha.refresh_from_db()
        self.assertEqual(self.linha.dados.get("siape"), "123")
        self.assertEqual(self.linha.dados_usuario["metadados"].get("siape"), "123")

    def test_aplicar_remove_dos_tres_lugares(self):
        call_command("limpar_metadado", "siape", "--aplicar", stdout=StringIO())

        self.assertEqual(
            metadados.dados_de(self.usuario),
            {"vinculo": "Servidor", "funcao": "Professor"},
        )
        self.linha.refresh_from_db()
        self.assertEqual(self.linha.dados, {"vinculo": "Servidor", "funcao": "Professor"})
        self.assertEqual(
            self.linha.dados_usuario,
            {"nome": "Limpa Teste", "cpf": "", "metadados": {"funcao": "Professor"}},
        )
