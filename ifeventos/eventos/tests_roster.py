"""Testes da pré-carga de alunos (planilha) e do completamento do 1º acesso."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from allauth.account.signals import user_signed_up

from eventos import metadados, roster
from eventos.models import AlunoRoster

U = get_user_model()
SENHA = "SenhaForte123!"
CPF_VALIDO = "123.456.789-09"
CPF_DIGITOS = "12345678909"

# Config mínima, com as mesmas regras do projeto (visibilidade por vínculo e
# `ano` dependente do curso), para exercitar o mapeamento sem depender do schema
# real da escola.
CONFIG = [
    {"chave": "vinculo", "rotulo": "Vínculo", "tipo": "escolha",
     "obrigatorio": True, "ordem": 1, "opcoes": ["Aluno", "Servidor"]},
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
     "opcoes_por": {
         "Informática": ["Primeiro ano", "Segundo ano", "Terceiro ano"],
         "Administração": ["Primeiro ano", "Segundo ano", "Terceiro ano"],
         "TPG": ["Primeiro período", "Segundo período"],
     },
     "visivel_quando": {"chave": "vinculo", "valores": ["Aluno"]}},
]


def linha(**kwargs):
    """Linha da planilha com os cabeçalhos reais (com acento, como no .xls)."""
    base = {
        "Matrícula": "0074812",
        "Nome": "Fulano de Tal",
        "CPF": CPF_VALIDO,
        "Código Curso": "PNIINFO",
        "Email Pessoal": "fulano@example.com",
        "Turma": "I1PNIINFO1",
    }
    base.update(kwargs)
    return base


class DecodificarTurmaTests(TestCase):
    def test_codigo_completo(self):
        self.assertEqual(
            roster.decodificar_turma("I1PNIINFO1"),
            {"ano": "Primeiro ano", "turma": "Turma 1"},
        )
        self.assertEqual(
            roster.decodificar_turma("I3PNIADMI2"),
            {"ano": "Terceiro ano", "turma": "Turma 2"},
        )

    def test_codigo_ausente_ou_invalido(self):
        self.assertEqual(roster.decodificar_turma("-"), {})
        self.assertEqual(roster.decodificar_turma(""), {})
        self.assertEqual(roster.decodificar_turma("I9ZZZZ1"), {})


class MontarDadosTests(TestCase):
    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_aluno_integrado(self):
        dados = roster.montar_dados({roster._chave(k): v for k, v in linha().items()})
        self.assertEqual(dados["vinculo"], "Aluno")
        self.assertEqual(dados["matricula"], "0074812")
        self.assertEqual(dados["curso"], "Informática")
        self.assertEqual(dados["ano"], "Primeiro ano")
        self.assertEqual(dados["turma"], "Turma 1")

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_tpg_sem_turma_fica_sem_ano_e_turma(self):
        dados = roster.montar_dados(
            {roster._chave(k): v for k, v in linha(**{"Código Curso": "PNTGER", "Turma": "-"}).items()}
        )
        self.assertEqual(dados["curso"], "TPG")
        self.assertNotIn("ano", dados)
        self.assertNotIn("turma", dados)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_pnedocin_fica_de_fora(self):
        self.assertEqual(
            roster.montar_dados(
                {roster._chave(k): v for k, v in linha(**{"Código Curso": "PNEDOCIN"}).items()}
            ),
            {},
        )


class ImportarLinhasTests(TestCase):
    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_importa_e_e_idempotente(self):
        relatorio = roster.importar_linhas([linha()])
        self.assertEqual(relatorio["importados"], 1)
        self.assertEqual(relatorio["erros"], 0)
        obj = AlunoRoster.objects.get(email="fulano@example.com")
        self.assertEqual(obj.cpf, CPF_DIGITOS)
        self.assertEqual(obj.dados["curso"], "Informática")

        relatorio = roster.importar_linhas([linha(**{"Nome": "Fulano Atualizado"})])
        self.assertEqual(relatorio["atualizados"], 1)
        self.assertEqual(AlunoRoster.objects.count(), 1)
        self.assertEqual(AlunoRoster.objects.get().nome, "Fulano Atualizado")

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_email_normalizado_para_minusculas(self):
        roster.importar_linhas([linha(**{"Email Pessoal": "FULANO@Example.COM"})])
        self.assertTrue(AlunoRoster.objects.filter(email="fulano@example.com").exists())

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_pnedocin_e_cpf_invalido_sao_ignorados(self):
        relatorio = roster.importar_linhas([
            linha(**{"Código Curso": "PNEDOCIN", "Email Pessoal": "a@example.com"}),
            linha(**{"CPF": "111.111.111-11", "Email Pessoal": "b@example.com"}),
        ])
        self.assertEqual(relatorio["ignorados"], 2)
        self.assertEqual(AlunoRoster.objects.count(), 0)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_linha_sem_email_e_erro(self):
        relatorio = roster.importar_linhas([linha(**{"Email Pessoal": ""})])
        self.assertEqual(relatorio["erros"], 1)
        self.assertEqual(AlunoRoster.objects.count(), 0)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_reimportar_preserva_o_rastreio(self):
        from django.utils import timezone

        roster.importar_linhas([linha()])
        obj = AlunoRoster.objects.get()
        obj.usado_em = timezone.now()
        obj.confere = True
        obj.dados_usuario = {"metadados": {"curso": "Informática"}}
        obj.save(update_fields=["usado_em", "confere", "dados_usuario"])

        roster.importar_linhas([linha(**{"Nome": "Fulano Reimportado"})])

        obj.refresh_from_db()
        self.assertEqual(obj.nome, "Fulano Reimportado")
        self.assertIsNotNone(obj.usado_em)
        self.assertTrue(obj.confere)
        self.assertIsNotNone(obj.dados_usuario)


class DividirNomeTests(TestCase):
    def test_um_nome(self):
        self.assertEqual(roster.dividir_nome("Madonna"), ("Madonna", ""))

    def test_varios_nomes(self):
        self.assertEqual(roster.dividir_nome("Maria da Silva"), ("Maria", "da Silva"))

    def test_vazio_ou_none(self):
        self.assertEqual(roster.dividir_nome(""), ("", ""))
        self.assertEqual(roster.dividir_nome(None), ("", ""))


class CompletarDoRosterTests(TestCase):
    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def setUp(self):
        AlunoRoster.objects.create(
            email="aluno@example.com",
            nome="Aluno Teste",
            cpf=CPF_DIGITOS,
            dados={"vinculo": "Aluno", "matricula": "0074812",
                   "curso": "Informática", "ano": "Primeiro ano", "turma": "Turma 1"},
        )

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_preenche_metadados_e_cpf(self):
        user = U.objects.create_user(email="aluno@example.com", password=SENHA)
        self.assertTrue(roster.completar_do_roster(user))
        user.refresh_from_db()
        self.assertEqual(user.cpf, CPF_DIGITOS)
        dados = metadados.dados_de(user)
        self.assertEqual(dados["matricula"], "0074812")
        self.assertEqual(dados["turma"], "Turma 1")

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_nao_sobrescreve_o_que_a_pessoa_informou(self):
        user = U.objects.create_user(email="aluno@example.com", password=SENHA)
        metadados.salvar(user, {"vinculo": "Aluno", "matricula": "999",
                                "curso": "TPG"})
        roster.completar_do_roster(user)
        dados = metadados.dados_de(user)
        self.assertEqual(dados["matricula"], "999")
        self.assertEqual(dados["curso"], "TPG")
        self.assertNotIn("ano", dados)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_nao_preserva_cpf_existente(self):
        user = U.objects.create_user(email="aluno@example.com", password=SENHA)
        user.cpf = "52998224725"
        user.save(update_fields=["cpf"])
        roster.completar_do_roster(user)
        user.refresh_from_db()
        self.assertEqual(user.cpf, "52998224725")

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_email_fora_da_planilha_nao_faz_nada(self):
        user = U.objects.create_user(email="outro@example.com", password=SENHA)
        self.assertFalse(roster.completar_do_roster(user))
        self.assertEqual(metadados.dados_de(user), {})

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_preenche_nome_quando_vazio(self):
        user = U.objects.create_user(email="aluno@example.com", password=SENHA)
        roster.completar_do_roster(user)
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Aluno")
        self.assertEqual(user.last_name, "Teste")

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_nao_sobrescreve_nome_existente(self):
        user = U.objects.create_user(email="aluno@example.com", password=SENHA)
        user.first_name, user.last_name = "Nome", "Google"
        user.save(update_fields=["first_name", "last_name"])
        roster.completar_do_roster(user)
        user.refresh_from_db()
        self.assertEqual(user.first_name, "Nome")
        self.assertEqual(user.last_name, "Google")

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_marca_usado_e_confere_quando_bate(self):
        user = U.objects.create_user(email="aluno@example.com", password=SENHA)
        self.assertTrue(roster.completar_do_roster(user))
        linha = AlunoRoster.objects.get(email="aluno@example.com")
        self.assertIsNotNone(linha.usado_em)
        self.assertTrue(linha.confere)
        self.assertEqual(linha.dados_usuario["metadados"]["curso"], "Informática")

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_marca_diverge_e_guarda_o_que_a_pessoa_usou(self):
        user = U.objects.create_user(email="aluno@example.com", password=SENHA)
        metadados.salvar(user, {"vinculo": "Aluno", "matricula": "999",
                                "curso": "Informática"})
        self.assertTrue(roster.completar_do_roster(user))
        linha = AlunoRoster.objects.get(email="aluno@example.com")
        self.assertFalse(linha.confere)
        self.assertEqual(linha.dados_usuario["metadados"]["matricula"], "999")

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_linha_nao_usada_fica_com_confere_nulo(self):
        linha = AlunoRoster.objects.get(email="aluno@example.com")
        self.assertIsNone(linha.usado_em)
        self.assertIsNone(linha.confere)


class SignalTests(TestCase):
    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_user_signed_up_completa_o_perfil(self):
        AlunoRoster.objects.create(
            email="novo@example.com", cpf=CPF_DIGITOS,
            dados={"vinculo": "Aluno", "matricula": "0074812", "curso": "Informática"},
        )
        user = U.objects.create_user(email="novo@example.com", password=SENHA)
        user_signed_up.send(sender=U, request=None, user=user)
        user.refresh_from_db()
        self.assertEqual(metadados.dados_de(user)["curso"], "Informática")
        self.assertEqual(user.cpf, CPF_DIGITOS)

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_sinal_sem_roster_nao_quebra(self):
        user = U.objects.create_user(email="sem-roster@example.com", password=SENHA)
        user_signed_up.send(sender=U, request=None, user=user)
        self.assertEqual(metadados.dados_de(user), {})


class AlunoRosterAdminFormTests(TestCase):
    """O admin valida o JSON `dados` e o CPF antes de gravar (não mais em silêncio)."""

    def _form(self, **extra):
        from eventos.admin import AlunoRosterForm

        data = {"email": "a@example.com", "nome": "X", "cpf": CPF_VALIDO,
                "dados": '{"vinculo": "Aluno", "matricula": "1", "curso": "Informática"}'}
        data.update(extra)
        return AlunoRosterForm(data=data)

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
    """GET /eventos/roster/ — pré-preenchimento do cadastro."""

    def setUp(self):
        AlunoRoster.objects.create(
            email="aluno@example.com", nome="Aluno Teste", cpf=CPF_DIGITOS,
            dados={"vinculo": "Aluno", "matricula": "0074812",
                   "curso": "Informática", "turma": "Turma 1", "ano": "Primeiro ano"},
        )
        self.url = reverse("eventos:roster_lookup")

    def test_acha_por_email_ignorando_maiusculas(self):
        resposta = self.client.get(self.url, {"email": "ALUNO@Example.com"})
        corpo = resposta.json()
        self.assertTrue(corpo["encontrado"])
        self.assertEqual(corpo["origem"], "email")
        self.assertEqual(corpo["dados"]["curso"], "Informática")
        self.assertEqual(corpo["cpf"], "123.456.789-09")
        self.assertEqual(corpo["first_name"], "Aluno")
        self.assertEqual(corpo["last_name"], "Teste")

    def test_fallback_por_cpf_quando_email_nao_bate(self):
        resposta = self.client.get(
            self.url, {"email": "ninguem@example.com", "cpf": "123.456.789-09"}
        )
        corpo = resposta.json()
        self.assertTrue(corpo["encontrado"])
        self.assertEqual(corpo["origem"], "cpf")

    def test_nao_encontrado(self):
        resposta = self.client.get(self.url, {"email": "ninguem@example.com"})
        self.assertEqual(resposta.json(), {"encontrado": False})
        self.assertEqual(resposta["Cache-Control"], "no-store")

    def test_metodo_diferente_de_get(self):
        # O endpoint é só leitura: POST é recusado (405 pelo @require_GET; no
        # servidor real o CSRF corta antes, com 403). Nunca 200.
        status = self.client.post(self.url).status_code
        self.assertIn(status, (403, 405))


