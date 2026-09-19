"""Testes da importação assistida da programação.

Cobrem o mapeamento por sinônimos, a montagem de data/hora/turno, a sanitização
do mapeamento da IA, a prévia sem gravar e o fluxo da tela (upload → prévia →
importação).
"""

from datetime import timedelta
from unittest import mock
from unittest.mock import AsyncMock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from asgiref.sync import async_to_sync

from eventos import importacao_assistida as imp
from eventos.models import Atividade, Evento, TipoAtividade

U = get_user_model()
SENHA = "SenhaForte123!"

CACHE_LOCMEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


class _FakeOpenAI:
    """Cliente OpenAI falso que devolve um mapeamento fixo."""

    def __init__(self, conteudo):
        resposta = mock.MagicMock()
        resposta.choices = [mock.MagicMock()]
        resposta.choices[0].message.content = conteudo
        resposta.usage = None
        self.chat = mock.MagicMock()
        self.chat.completions.create = AsyncMock(return_value=resposta)


class _FixturesMixin:
    def setUp(self):
        cache.clear()
        self.org = U.objects.create_user(
            email="org_imp@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento da Importação", description="d", local="Campus",
            data_inicio=hoje + timedelta(days=10),
            data_fim=hoje + timedelta(days=14),
            categoria="formacao", organizador=self.org,
        )

    def _csv(self, cabecalho, linhas):
        texto = "\n".join([cabecalho] + linhas) + "\n"
        return SimpleUploadedFile("programacao.csv", texto.encode("utf-8"), content_type="text/csv")


class MapeamentoTests(TestCase):
    """Camada determinística: sinônimos, parser e montagem das linhas."""

    def test_sinonimos_mapeiam_colunas_comuns(self):
        cabecalhos = ["titulo da atividade", "local adequado", "tipo de atividade",
                      "dia", "hora inicio", "hora fim", "e-mail do palestrante"]
        mapa = imp.mapear_por_sinonimos(cabecalhos)

        self.assertEqual(mapa["titulo"], "titulo da atividade")
        self.assertEqual(mapa["local"], "local adequado")
        self.assertEqual(mapa["tipo"], "tipo de atividade")
        self.assertEqual(mapa["data"], "dia")
        self.assertEqual(mapa["hora_inicio"], "hora inicio")
        self.assertEqual(mapa["palestrantes"], "e-mail do palestrante")

    def test_validar_exige_titulo_e_evita_coluna_repetida(self):
        cabecalhos = ["a", "b"]
        erros, _avisos = imp.validar_mapeamento({"local": "a", "descricao": "a"}, cabecalhos)
        self.assertTrue(any("título" in e for e in erros))
        self.assertTrue(any("mais de um campo" in e for e in erros))

    def test_validar_avisa_sem_horario(self):
        _erros, avisos = imp.validar_mapeamento({"titulo": "a"}, ["a"])
        self.assertTrue(any("Início" in a for a in avisos))

    def test_montar_linha_com_data_e_horas(self):
        linha = imp.montar_linha(
            {"titulo": "Oficina", "data": "10/11/2026", "hora_inicio": "8:00",
             "hora_fim": "10h30", "tipo": "Oficina"},
            self._evento(),
        )
        self.assertEqual(linha["inicio"], "10/11/2026 08:00")
        self.assertEqual(linha["fim"], "10/11/2026 10:30")

    def test_montar_linha_usa_turno_quando_falta_hora(self):
        linha = imp.montar_linha(
            {"titulo": "Palestra", "data": "10/11/2026", "turno": "Manhã"},
            self._evento(),
        )
        self.assertEqual(linha["inicio"], "10/11/2026 08:00")
        self.assertEqual(linha["fim"], "10/11/2026 12:00")

    def test_montar_linha_aceita_inicio_direto(self):
        linha = imp.montar_linha(
            {"titulo": "Mesa", "inicio": "10/11/2026 14:00", "fim": "10/11/2026 16:00"},
            self._evento(),
        )
        self.assertEqual(linha["inicio"], "10/11/2026 14:00")
        self.assertEqual(linha["fim"], "10/11/2026 16:00")

    def test_sanitizar_mapeamento_ia_descarta_invalidos(self):
        limpo = imp.sanitizar_mapeamento_ia(
            {"mapeamento": {"inexistente": "col", "titulo": "col", "local": "sumiu"}},
            ["col"],
        )
        self.assertEqual(limpo, {"titulo": "col"})

    def _evento(self):
        from types import SimpleNamespace

        return SimpleNamespace(data_inicio=timezone.localdate())


class PreviaTests(_FixturesMixin, TestCase):
    def test_previa_nao_grava(self):
        linhas = [imp.montar_linha(
            {"titulo": "Oficina A", "data": self.evento.data_inicio.strftime("%d/%m/%Y"),
             "hora_inicio": "08:00", "hora_fim": "10:00", "tipo": "Oficina"},
            self.evento,
        )]
        relatorio = imp.previsualizar(self.evento, linhas)

        self.assertEqual(relatorio["criadas"], 1)
        self.assertEqual(Atividade.objects.filter(evento=self.evento).count(), 0)


@override_settings(CACHES=CACHE_LOCMEM)
class SugerirMapeamentoTests(_FixturesMixin, TransactionTestCase):
    def test_sem_ia_usa_sinonimos(self):
        cabecalhos = ["titulo", "local", "tipo"]
        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            resultado = async_to_sync(imp.sugerir_mapeamento)(
                cabecalhos, [], self.evento
            )
        self.assertEqual(resultado["origem"], "sinonimos")
        self.assertEqual(resultado["mapeamento"]["titulo"], "titulo")

    def test_ia_completa_colunas(self):
        cabecalhos = ["assunto", "onde"]
        fake = _FakeOpenAI('{"mapeamento": {"titulo": "assunto", "local": "onde"}}')
        with mock.patch("eventos.services.get_openai_client", return_value=fake):
            resultado = async_to_sync(imp.sugerir_mapeamento)(
                cabecalhos, [{"assunto": "X", "onde": "Y"}], self.evento
            )
        self.assertEqual(resultado["origem"], "ia")
        self.assertEqual(resultado["mapeamento"], {"titulo": "assunto", "local": "onde"})


@override_settings(CACHES=CACHE_LOCMEM)
class ImportacaoViewTests(_FixturesMixin, TransactionTestCase):
    def test_permissao_exige_organizador(self):
        pessoa = U.objects.create_user(
            email="pessoa_imp@example.com", password=SENHA, cpf="11144477735"
        )
        self.client.force_login(pessoa)
        resposta = self.client.get(
            reverse("organizador:importar_programacao", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 403)

    def test_fluxo_upload_previa_importacao(self):
        self.client.force_login(self.org)
        data = self.evento.data_inicio.strftime("%d/%m/%Y")
        arquivo = self._csv(
            "titulo da atividade,local adequado,tipo de atividade,dia,hora inicio,hora fim",
            ["Oficina de robótica,Auditório,Oficina,%s,08:00,10:00" % data],
        )
        url = reverse("organizador:importar_programacao", args=[self.evento.id])

        with mock.patch("eventos.services.get_openai_client", side_effect=RuntimeError("x")):
            resposta = self.client.post(url, {"acao": "preview", "arquivo": arquivo})

        self.assertEqual(resposta.status_code, 200)
        token = resposta.context["token"]
        self.assertEqual(resposta.context["previa"]["criadas"], 1)
        self.assertEqual(Atividade.objects.filter(evento=self.evento).count(), 0)

        # Confirma a importação reusando o mapeamento sugerido.
        mapeamento = resposta.context["mapeamento"]
        dados = {"acao": "importar", "token": token}
        for chave, origem in mapeamento.items():
            dados["map_%s" % chave] = origem
        resposta = self.client.post(url, dados)

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.context["concluido"])
        self.assertEqual(resposta.context["relatorio"]["criadas"], 1)
        self.assertEqual(Atividade.objects.filter(evento=self.evento).count(), 1)


class AncoragemTests(_FixturesMixin, TestCase):
    """Contexto do banco e normalizações que ancoram o copiloto."""

    def test_dossie_tem_catalogos_sem_pii(self):
        from eventos import contexto_ia

        dados = contexto_ia.dossie(self.evento)
        self.assertIn("tipos", dados)
        self.assertIn("espacos", dados)

        texto = contexto_ia.resumo_texto(dados)
        self.assertNotIn("org_imp@example.com", texto)
        self.assertNotIn("12345678909", texto)

    def test_sanitizar_normalizacoes(self):
        limpo = imp.sanitizar_normalizacoes({
            "tipo": {"  Palestra  ": "Palestra"}, "local": {"Auditório": "Auditório"},
        })
        self.assertEqual(limpo["tipo"], {"Palestra": "Palestra"})

    def test_aplicar_mapeamento_aplica_normalizacao(self):
        linhas = [{"t": "Oficina X", "tp": "palestra", "lc": "lab 1"}]
        mapeamento = {"titulo": "t", "tipo": "tp", "local": "lc"}
        canonicas = imp.aplicar_mapeamento(
            linhas, mapeamento, self.evento,
            {"tipo": {"palestra": "Palestra"}, "local": {"lab 1": "Laboratório 1"}},
        )
        self.assertEqual(canonicas[0]["tipo"], "Palestra")
        self.assertEqual(canonicas[0]["local"], "Laboratório 1")

    def test_detectar_imagens(self):
        linhas = [
            {"titulo": "A", "foto": "https://drive.google.com/file/d/abc"},
            {"titulo": "B", "foto": ""},
        ]
        achadas = imp.detectar_imagens(linhas, {"imagem": "foto"})
        self.assertEqual(len(achadas), 1)
        self.assertIn("drive.google", achadas[0]["url"])

    def test_detectar_duplicatas(self):
        Atividade.objects.create(
            evento=self.evento, titulo="Oficina X", descricao="d", tipo=self.tipo,
            n_vagas=1, data_hora_inicio=timezone.now(), data_hora_fim=timezone.now(),
        )
        repetidos = imp.detectar_duplicatas([{"titulo": "Oficina X"}], self.evento)
        self.assertEqual(repetidos, ["Oficina X"])

    def test_valores_faltantes(self):
        canonicas = [{"titulo": "A", "tipo": "Novo Tipo", "local": "Sala Nova"}]
        faltantes = imp.valores_faltantes(canonicas, self.evento)
        self.assertIn("Novo Tipo", faltantes["tipos"])
        self.assertIn("Sala Nova", faltantes["locais"])
