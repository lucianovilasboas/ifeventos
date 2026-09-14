"""Testes da API — palestrantes e o campo `local` da atividade.

Cobrem o contrato novo: /api/v1/palestrantes/ (só organizador, inclusive na
leitura, sem DELETE, POST idempotente por e-mail) e `local` em atividades
(aceito, persistido e devolvido; `palestrantes` deixa de ser obrigatório).
"""

from datetime import date, datetime, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from eventos.models import Atividade, Evento, Participante, TipoAtividade

U = get_user_model()
SENHA = "SenhaForte123!"


class _BaseApiTests(TestCase):
    def setUp(self):
        self.organizador = U.objects.create_user(
            email="api_org@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True, is_participante=False,
        )
        self.participante = U.objects.create_user(
            email="api_part@example.com", password=SENHA, cpf="11144477735",
        )
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento", description="d", local="Auditório",
            data_inicio=date(2026, 10, 1), data_fim=date(2026, 10, 2),
            categoria="formacao", organizador=self.organizador,
        )
        self.client = APIClient()

    def _autenticar(self, usuario):
        self.client.force_authenticate(user=usuario)

    def _criar_palestrante(self, **extra):
        dados = {
            "first_name": "Ana",
            "last_name": "Souza",
            "email": "ana@example.com",
            "cpf": "123.456.789-09",
            "telefone": "31999999999",
        }
        dados.update(extra)
        return self.client.post("/api/v1/palestrantes/", dados, format="json")

    def _dados_atividade(self, **extra):
        dados = {
            "evento": self.evento.id,
            "titulo": "Oficina",
            "descricao": "d",
            "local": "Sala 12",
            "tipo": self.tipo.id,
            "data_hora_inicio": "2026-10-01T08:00:00Z",
            "data_hora_fim": "2026-10-01T09:00:00Z",
            "n_vagas": 30,
            "emite_certificado": False,
        }
        dados.update(extra)
        return dados


class PalestranteApiTests(_BaseApiTests):
    def test_organizador_cria_palestrante(self):
        self._autenticar(self.organizador)
        resposta = self._criar_palestrante()
        self.assertEqual(resposta.status_code, 201, resposta.content)

        palestrante = Participante.objects.get(email="ana@example.com")
        self.assertTrue(palestrante.is_palestrante)
        self.assertTrue(palestrante.is_participante)
        self.assertFalse(palestrante.has_usable_password())
        self.assertEqual(palestrante.cpf, "12345678909")  # normalizado
        self.assertEqual(resposta.data["nome_completo"], "Ana Souza")

    def test_post_repetido_atualiza_sem_duplicar(self):
        self._autenticar(self.organizador)
        self._criar_palestrante()

        resposta = self._criar_palestrante(first_name="Ana Maria")
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertEqual(Participante.objects.filter(email="ana@example.com").count(), 1)
        self.assertEqual(Participante.objects.get(email="ana@example.com").first_name, "Ana Maria")
        self.assertTrue(Participante.objects.get(email="ana@example.com").is_palestrante)

    def test_participante_nao_pode_criar(self):
        self._autenticar(self.participante)
        self.assertEqual(self._criar_palestrante().status_code, 403)

    def test_participante_nao_pode_listar(self):
        self._autenticar(self.participante)
        self.assertEqual(self.client.get("/api/v1/palestrantes/").status_code, 403)

    def test_anonimo_nao_pode_listar(self):
        self.assertIn(
            self.client.get("/api/v1/palestrantes/").status_code, (401, 403)
        )

    def test_organizador_lista(self):
        self._autenticar(self.organizador)
        self._criar_palestrante()
        resposta = self.client.get("/api/v1/palestrantes/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["count"], 1)

    def test_delete_nao_permitido(self):
        self._autenticar(self.organizador)
        self._criar_palestrante()
        palestrante = Participante.objects.get(email="ana@example.com")
        resposta = self.client.delete(f"/api/v1/palestrantes/{palestrante.id}/")
        self.assertEqual(resposta.status_code, 405)


class AtividadeLocalApiTests(_BaseApiTests):
    def test_criar_atividade_com_local(self):
        self._autenticar(self.organizador)
        resposta = self.client.post(
            "/api/v1/atividades/", self._dados_atividade(), format="json"
        )
        self.assertEqual(resposta.status_code, 201, resposta.content)
        self.assertEqual(resposta.data["local"], "Sala 12")

        # O POST de atividade não devolve `id` (o serializer de escrita não o
        # expõe); buscamos pelo título só para conferir a persistência.
        atividade = Atividade.objects.get(titulo="Oficina")
        self.assertEqual(atividade.local, "Sala 12")

    def test_criar_atividade_sem_palestrantes(self):
        self._autenticar(self.organizador)
        dados = self._dados_atividade()
        dados.pop("palestrantes", None)
        resposta = self.client.post("/api/v1/atividades/", dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.content)
        self.assertEqual(resposta.data["palestrantes"], [])

    def test_patch_sem_palestrantes_nao_apaga_os_existentes(self):
        self._autenticar(self.organizador)
        palestrante = U.objects.create_user(
            email="pal@example.com", password=SENHA, cpf="12345678909",
            is_palestrante=True,
        )
        atividade = Atividade.objects.create(
            evento=self.evento, titulo="Oficina", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 10, 1, 8, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 1, 9, 0, tzinfo=tz.utc),
            n_vagas=30,
        )
        atividade.palestrantes.add(palestrante)

        resposta = self.client.patch(
            f"/api/v1/atividades/{atividade.id}/", {"local": "Sala 5"}, format="json"
        )
        self.assertEqual(resposta.status_code, 200, resposta.content)
        atividade.refresh_from_db()
        self.assertEqual(atividade.local, "Sala 5")
        self.assertEqual(list(atividade.palestrantes.values_list("id", flat=True)), [palestrante.id])
