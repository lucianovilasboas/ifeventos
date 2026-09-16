"""Testes da pré-carga genérica (planilha) e do completamento do 1º acesso."""

import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from allauth.account.signals import user_signed_up

from eventos import metadados, roster
from eventos.models import PessoaRoster

U = get_user_model()
SENHA = "SenhaForte123!"
CPF_VALIDO = "123.456.789-09"
CPF_DIGITOS = "12345678909"

# Config genérica com os vínculos do projeto (Aluno x Servidor têm campos
# próprios; os demais só o vínculo), para exercitar tudo sem depender do schema
# real da escola.
CONFIG = [
    {"chave": "vinculo", "rotulo": "Vínculo", "tipo": "escolha",
     "obrigatorio": True, "ordem": 1,
     "opcoes": ["Aluno", "Servidor", "Colaborador", "Estagiário", "Comunidade externa"]},
    {"chave": "matricula", "rotulo": "Matrícula", "tipo": "texto",
     "obrigatorio": True, "ordem": 2,
     "visivel_quando": {"chave": "vinculo", "valores": ["Aluno"]}},
    {"chave": "curso", "rotulo": "Curso", "tipo": "escolha",
     "obrigatorio": True, "ordem": 3, "opcoes": ["Informática", "Administração", "TPG"],
     "visivel_quando": {"chave": "vinculo", "valores": ["Aluno"]}},
    {"chave": "turma", "rotulo": "Turma", "tipo": "escolha", "ordem": 4,
     "opcoes": ["Turma 1", "Turma 2"],
     "visivel_quando": {"chave": "vinculo", "valores": ["Aluno"]}},
    {"chave": "ano", "rotulo": "Ano/Período", "tipo": "escolha", "ordem": 5,
     "depende_de": "curso",
     "opcoes_por": {"Informática": ["Primeiro ano", "Segundo ano", "Terceiro ano"],
                    "TPG": ["Primeiro período", "Segundo período"]},
     "visivel_quando": {"chave": "vinculo", "valores": ["Aluno"]}},
    {"chave": "funcao", "rotulo": "Função", "tipo": "escolha",
     "obrigatorio": True, "ordem": 6, "opcoes": ["Professor", "Técnico administrativo"],
     "visivel_quando": {"chave": "vinculo", "valores": ["Servidor"]}},
    {"chave": "siape", "rotulo": "SIAPE", "tipo": "texto", "ordem": 7,
     "visivel_quando": {"chave": "vinculo", "valores": ["Servidor"]}},
]


def linha(**kwargs):
    """Linha genérica de Aluno (chaves já normalizadas)."""
    base = {"email": "aluno@example.com", "nome": "Aluno Teste", "cpf": CPF_DIGITOS,
            "vinculo": "Aluno", "matricula": "0074812", "curso": "Informática",
            "turma": "Turma 1", "ano": "Primeiro ano"}
    base.update(kwargs)
    return base


def linha_servidor(**kwargs):
    base = {"email": "servidor@example.com", "nome": "Maria Souza", "cpf": CPF_DIGITOS,
            "vinculo": "Servidor", "funcao": "Professor", "siape": "1234567"}
    base.update(kwargs)
    return base


class DividirNomeTests(TestCase):
    def test_um_nome(self):
        self.assertEqual(roster.dividir_nome("Madonna"), ("Madonna", ""))

    def test_varios_nomes(self):
        self.assertEqual(roster.dividir_nome("Maria da Silva"), ("Maria", "da Silva"))

    def test_vazio_ou_none(self):
        self.assertEqual(roster.dividir_nome(""), ("", ""))
        self.assertEqual(roster.dividir_nome(None), ("", ""))


class ImportarLinhasTests(TestCase):
    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_importa_aluno_e_servidor_no_mesmo_arquivo(self):
        relatorio = roster.importar_linhas([linha(), linha_servidor()])
        self.assertEqual(relatorio["importados"], 2)
        self.assertEqual(relatorio["erros"], 0)

        aluno = PessoaRoster.objects.get(email="aluno@example.com")
        self.assertEqual(aluno.vinculo, "Aluno")  # coluna espelho
        self.assertEqual(aluno.dados["curso"], "Informática")

        servidor = PessoaRoster.objects.get(email="servidor@example.com")
        self.assertEqual(servidor.vinculo, "Servidor")
        self.assertEqual(servidor.dados["funcao"], "Professor")
        self.assertNotIn("matricula", servidor.dados)  # não se aplica ao vínculo

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_idempotente_e_normaliza_email(self):
        roster.importar_linhas([linha(**{"email": "FULANO@Example.COM"})])
        self.assertTrue(PessoaRoster.objects.filter(email="fulano@example.com").exists())

        relatorio = roster.importar_linhas([linha(**{"email": "fulano@example.com",
                                                     "nome": "Atualizado"})])
        self.assertEqual(relatorio["atualizados"], 1)
        self.assertEqual(PessoaRoster.objects.count(), 1)
        self.assertEqual(PessoaRoster.objects.get().nome, "Atualizado")

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_servidor_sem_funcao_e_erro(self):
        relatorio = roster.importar_linhas([
            {"email": "s@example.com", "vinculo": "Servidor"}
        ])
        self.assertEqual(relatorio["erros"], 1)
        self.assertEqual(PessoaRoster.objects.count(), 0)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_cpf_invalido_e_sem_email_sao_erros(self):
        relatorio = roster.importar_linhas([
            linha(**{"cpf": "111.111.111-11"}),
            linha(**{"email": ""}),
        ])
        self.assertEqual(relatorio["erros"], 2)
        self.assertEqual(PessoaRoster.objects.count(), 0)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_coluna_extra_e_valor_inaplicavel_geram_aviso(self):
        relatorio = roster.importar_linhas([
            linha(**{"telefone": "31999998888", "funcao": "Professor"})
        ])
        avisos = " | ".join(relatorio["linhas"][0]["avisos"])
        self.assertIn("telefone", avisos)          # fora do schema
        self.assertIn("Função", avisos)            # não se aplica a Aluno

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_reimportar_preserva_o_rastreio(self):
        from django.utils import timezone

        roster.importar_linhas([linha()])
        obj = PessoaRoster.objects.get()
        obj.usado_em = timezone.now()
        obj.confere = True
        obj.dados_usuario = {"metadados": {"curso": "Informática"}}
        obj.save(update_fields=["usado_em", "confere", "dados_usuario"])

        roster.importar_linhas([linha(**{"nome": "Reimportado"})])

        obj.refresh_from_db()
        self.assertEqual(obj.nome, "Reimportado")
        self.assertIsNotNone(obj.usado_em)
        self.assertTrue(obj.confere)


class LeituraArquivoTests(TestCase):
    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_importa_csv_e_xlsx(self):
        from openpyxl import Workbook

        caminho_csv = os.path.join(self.dir, "pessoas.csv")
        with open(caminho_csv, "w", encoding="utf-8-sig", newline="") as f:
            f.write("email;nome;cpf;vinculo;matricula;curso;turma;ano\n")
            f.write("aluno@example.com;Aluno Teste;12345678909;Aluno;0074812;"
                    "Informática;Turma 1;Primeiro ano\n")

        caminho_xlsx = os.path.join(self.dir, "pessoas.xlsx")
        livro = Workbook()
        aba = livro.active
        aba.append(["email", "nome", "cpf", "vinculo", "funcao", "siape"])
        aba.append(["servidor@example.com", "Maria Souza", "12345678909",
                    "Servidor", "Professor", "1234567"])
        livro.save(caminho_xlsx)

        r1 = roster.importar_arquivo(caminho_csv)
        r2 = roster.importar_arquivo(caminho_xlsx)

        self.assertEqual(r1["importados"], 1)
        self.assertEqual(r2["importados"], 1)
        self.assertTrue(PessoaRoster.objects.filter(email="aluno@example.com").exists())
        self.assertTrue(PessoaRoster.objects.filter(email="servidor@example.com").exists())

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_extensao_nao_suportada(self):
        caminho = os.path.join(self.dir, "arquivo.txt")
        open(caminho, "w").close()
        with self.assertRaises(ValueError):
            roster.importar_arquivo(caminho)


class ModeloRosterCommandTests(TestCase):
    """O comando `modelo_roster` gera um arquivo válido e importável."""

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_gera_csv_com_uma_linha_por_vinculo(self):
        saida = os.path.join(self.dir, "modelo.csv")
        call_command("modelo_roster", saida=saida)
        self.assertTrue(os.path.exists(saida))

        with open(saida, encoding="utf-8-sig") as f:
            linhas = [l for l in f.read().splitlines() if l.strip()]
        self.assertEqual(linhas[0].split(";"), roster.cabecalhos())
        # 1 cabeçalho + 5 vínculos
        self.assertEqual(len(linhas), 1 + 5)

        # O próprio modelo é importável (valida vínculo, CPF e campos exigidos).
        relatorio = roster.importar_arquivo(saida)
        self.assertEqual(relatorio["erros"], 0)
        self.assertEqual(relatorio["importados"], 5)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_gera_xlsx(self):
        saida = os.path.join(self.dir, "modelo.csv")  # vira .xlsx
        call_command("modelo_roster", saida=saida, xlsx=True)
        destino = os.path.join(self.dir, "modelo.xlsx")
        self.assertTrue(os.path.exists(destino))
        self.assertEqual(roster.importar_arquivo(destino)["erros"], 0)


class CompletarDoRosterTests(TestCase):
    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_aluno_preenche_metadados_cpf_e_nome_e_marca(self):
        PessoaRoster.objects.create(email="aluno@example.com", nome="Aluno Teste",
                                    cpf=CPF_DIGITOS, dados=linha())
        user = U.objects.create_user(email="aluno@example.com", password=SENHA)
        self.assertTrue(roster.completar_do_roster(user))
        user.refresh_from_db()

        self.assertEqual(user.cpf, CPF_DIGITOS)
        self.assertEqual(user.first_name, "Aluno")
        self.assertEqual(user.last_name, "Teste")
        self.assertEqual(metadados.dados_de(user)["turma"], "Turma 1")

        linha_db = PessoaRoster.objects.get(email="aluno@example.com")
        self.assertIsNotNone(linha_db.usado_em)
        self.assertTrue(linha_db.confere)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_servidor_preenche_funcao_e_siape(self):
        PessoaRoster.objects.create(email="servidor@example.com", nome="Maria Souza",
                                    dados=linha_servidor())
        user = U.objects.create_user(email="servidor@example.com", password=SENHA)
        self.assertTrue(roster.completar_do_roster(user))

        dados = metadados.dados_de(user)
        self.assertEqual(dados["vinculo"], "Servidor")
        self.assertEqual(dados["funcao"], "Professor")
        self.assertEqual(dados["siape"], "1234567")

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_nao_sobrescreve_o_que_a_pessoa_informou(self):
        PessoaRoster.objects.create(email="aluno@example.com", dados=linha())
        user = U.objects.create_user(email="aluno@example.com", password=SENHA)
        metadados.salvar(user, {"vinculo": "Aluno", "matricula": "999",
                                "curso": "Informática"})
        roster.completar_do_roster(user)
        dados = metadados.dados_de(user)
        self.assertEqual(dados["matricula"], "999")
        linha_db = PessoaRoster.objects.get()
        self.assertFalse(linha_db.confere)  # divergiu da planilha
        self.assertEqual(linha_db.dados_usuario["metadados"]["matricula"], "999")

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_email_fora_da_planilha_nao_faz_nada(self):
        user = U.objects.create_user(email="outro@example.com", password=SENHA)
        self.assertFalse(roster.completar_do_roster(user))
        self.assertEqual(metadados.dados_de(user), {})

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_linha_nao_usada_fica_com_confere_nulo(self):
        PessoaRoster.objects.create(email="aluno@example.com", dados=linha())
        self.assertIsNone(PessoaRoster.objects.get().confere)


class SignalTests(TestCase):
    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_user_signed_up_completa_o_perfil(self):
        PessoaRoster.objects.create(email="novo@example.com", nome="Aluno Teste",
                                    cpf=CPF_DIGITOS, dados=linha(**{"email": "novo@example.com"}))
        user = U.objects.create_user(email="novo@example.com", password=SENHA)
        user_signed_up.send(sender=U, request=None, user=user)
        user.refresh_from_db()
        self.assertEqual(metadados.dados_de(user)["curso"], "Informática")
        self.assertEqual(user.cpf, CPF_DIGITOS)


class PessoaRosterAdminFormTests(TestCase):
    """O admin valida o JSON `dados` e o CPF antes de gravar."""

    def _form(self, **extra):
        from eventos.admin import PessoaRosterForm

        data = {"email": "a@example.com", "nome": "X", "cpf": CPF_VALIDO,
                "dados": '{"vinculo": "Aluno", "matricula": "1", "curso": "Informática"}'}
        data.update(extra)
        return PessoaRosterForm(data=data)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_dados_validos_passam_e_cpf_normaliza(self):
        form = self._form()
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cpf"], CPF_DIGITOS)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_curso_fora_das_opcoes_bloqueia(self):
        form = self._form(
            dados='{"vinculo": "Aluno", "matricula": "1", "curso": "Informatica"}'
        )
        self.assertFalse(form.is_valid())
        self.assertIn("dados", form.errors)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_cpf_invalido_bloqueia(self):
        self.assertIn("cpf", self._form(cpf="111.111.111-11").errors)


class RosterLookupEndpointTests(TestCase):
    """GET /eventos/roster/ — pré-preenchimento do cadastro (genérico)."""

    def setUp(self):
        PessoaRoster.objects.create(email="aluno@example.com", nome="Aluno Teste",
                                    cpf=CPF_DIGITOS, dados=linha())
        PessoaRoster.objects.create(email="servidor@example.com", nome="Maria Souza",
                                    cpf="52998224725", dados=linha_servidor())
        self.url = reverse("eventos:roster_lookup")

    def test_acha_aluno_por_email(self):
        corpo = self.client.get(self.url, {"email": "ALUNO@Example.com"}).json()
        self.assertTrue(corpo["encontrado"])
        self.assertEqual(corpo["origem"], "email")
        self.assertEqual(corpo["dados"]["curso"], "Informática")
        self.assertEqual(corpo["first_name"], "Aluno")
        self.assertEqual(corpo["last_name"], "Teste")

    def test_acha_servidor_por_cpf(self):
        corpo = self.client.get(
            self.url, {"email": "nao@example.com", "cpf": "529.982.247-25"}
        ).json()
        self.assertEqual(corpo["origem"], "cpf")
        self.assertEqual(corpo["dados"]["funcao"], "Professor")

    def test_nao_encontrado(self):
        resposta = self.client.get(self.url, {"email": "ninguem@example.com"})
        self.assertEqual(resposta.json(), {"encontrado": False})
        self.assertEqual(resposta["Cache-Control"], "no-store")

    def test_metodo_diferente_de_get(self):
        status = self.client.post(self.url).status_code
        self.assertIn(status, (403, 405))
