"""Testes da API — palestrantes e o campo `local` da atividade.

Cobrem o contrato novo: /api/v1/palestrantes/ (só organizador, inclusive na
leitura, sem DELETE, POST idempotente por e-mail) e `local` em atividades
(aceito, persistido e devolvido; `palestrantes` deixa de ser obrigatório).
"""

from datetime import date, datetime, timedelta, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from django.utils import timezone

from eventos.crachas import gerar_token_atividade
from eventos.models import (
    Atividade,
    Certificado,
    Evento,
    Inscricao,
    Participante,
    Presenca,
    PresencaCancelada,
    TipoAtividade,
)

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


class MetadadosApiTests(_BaseApiTests):
    """Metadados na API: palestrante, /meu-perfil/, /metadados/ e import."""

    def test_palestrante_traz_metadados(self):
        self._autenticar(self.organizador)
        resposta = self._criar_palestrante(
            metadados={"vinculo": "Servidor", "funcao": "Professor"}
        )
        self.assertEqual(resposta.status_code, 201, resposta.content)
        self.assertEqual(
            resposta.data["metadados"], {"vinculo": "Servidor", "funcao": "Professor"}
        )

    def test_meu_perfil_get_e_patch(self):
        self._autenticar(self.participante)
        inicial = self.client.get("/api/v1/meu-perfil/")
        self.assertEqual(inicial.status_code, 200)
        self.assertEqual(inicial.data["metadados"], {})

        resposta = self.client.patch(
            "/api/v1/meu-perfil/",
            {"metadados": {"vinculo": "Aluno", "matricula": "1", "curso": "TPG",
                           "ano": "Primeiro período"}},
            format="json",
        )
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertEqual(resposta.data["metadados"]["curso"], "TPG")

    def test_meu_perfil_recusa_dependencia_invalida(self):
        self._autenticar(self.participante)
        resposta = self.client.patch(
            "/api/v1/meu-perfil/",
            {"metadados": {"vinculo": "Aluno", "matricula": "1", "curso": "TPG",
                           "ano": "Primeiro ano"}},
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)

    def test_meu_perfil_descarta_campos_ocultos(self):
        self._autenticar(self.participante)
        resposta = self.client.patch(
            "/api/v1/meu-perfil/",
            {"metadados": {"vinculo": "Comunidade externa", "matricula": "1"}},
            format="json",
        )
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertEqual(resposta.data["metadados"], {"vinculo": "Comunidade externa"})

    def test_metadados_config_exige_organizador(self):
        self._autenticar(self.participante)
        self.assertEqual(self.client.get("/api/v1/metadados/").status_code, 403)

        self._autenticar(self.organizador)
        resposta = self.client.get("/api/v1/metadados/")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("vinculo", [c["chave"] for c in resposta.data["campos"]])

    def test_importar_metadados_em_lote(self):
        self._autenticar(self.organizador)
        resposta = self.client.post(
            "/api/v1/participantes/importar-metadados/",
            {"linhas": [{
                "email": self.participante.email, "vinculo": "Aluno",
                "matricula": "1", "curso": "TPG",
            }]},
            format="json",
        )
        self.assertEqual(resposta.status_code, 200, resposta.content)
        self.assertEqual(resposta.data["atualizados"], 1)
        self.participante.refresh_from_db()
        self.assertEqual(self.participante.metadados.dados["curso"], "TPG")

    def test_evento_traz_n_atividades(self):
        self._autenticar(self.organizador)
        self.client.post("/api/v1/atividades/", self._dados_atividade(), format="json")
        resposta = self.client.get(f"/api/v1/eventos/{self.evento.id}/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["n_atividades"], 1)


class AtividadeCicloApiTests(_BaseApiTests):
    """O ciclo rascunho/proposta aparece na leitura; `publicada` é escrevível."""

    def _proposta(self, situacao=Atividade.SITUACAO_PENDENTE, publicada=False, **extra):
        dados = {
            "evento": self.evento,
            "titulo": "Proposta da comunidade",
            "descricao": "d",
            "local": "Sala 12",
            "tipo": self.tipo,
            "data_hora_inicio": datetime(2026, 10, 1, 8, 0, tzinfo=tz.utc),
            "data_hora_fim": datetime(2026, 10, 1, 9, 0, tzinfo=tz.utc),
            "n_vagas": 10,
            "situacao": situacao,
            "publicada": publicada,
            "proponente": self.participante,
        }
        dados.update(extra)
        return Atividade.objects.create(**dados)

    def test_organizador_ve_o_ciclo_e_o_proponente(self):
        atividade = self._proposta(tipo_sugerido="Oficina")
        self._autenticar(self.organizador)

        dados = self.client.get(f"/api/v1/atividades/{atividade.id}/").json()

        self.assertFalse(dados["publicada"])
        self.assertEqual(dados["situacao"], "pendente")
        self.assertEqual(dados["situacao_rotulo"], "Aguardando aprovação")
        self.assertEqual(dados["tipo_sugerido"], "Oficina")
        self.assertEqual(dados["proponente"]["id"], self.participante.pk)
        self.assertEqual(dados["motivo_rejeicao"], "")

    def test_anonimo_nao_ve_o_proponente_nem_o_rascunho(self):
        aprovada = self._proposta(publicada=True, situacao=Atividade.SITUACAO_APROVADA)
        pendente = self._proposta(publicada=False)
        self.client.force_authenticate(user=None)

        publica = self.client.get(f"/api/v1/atividades/{aprovada.id}/")

        self.assertEqual(publica.status_code, 200)
        self.assertIsNone(publica.json()["proponente"], "propôs é dado pessoal")
        self.assertEqual(
            self.client.get(f"/api/v1/atividades/{pendente.id}/").status_code, 404
        )

    def test_proponente_ve_a_si_mesmo_na_atividade_aprovada(self):
        aprovada = self._proposta(publicada=True, situacao=Atividade.SITUACAO_APROVADA)
        self._autenticar(self.participante)

        dados = self.client.get(f"/api/v1/atividades/{aprovada.id}/").json()

        self.assertEqual(dados["proponente"]["id"], self.participante.pk)

    def test_organizador_despublica_pela_api(self):
        atividade = Atividade.objects.create(
            evento=self.evento, titulo="Publicada", descricao="d", local="Sala",
            tipo=self.tipo,
            data_hora_inicio=datetime(2026, 10, 1, 8, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 1, 9, 0, tzinfo=tz.utc),
            n_vagas=10, publicada=True,
        )
        self._autenticar(self.organizador)

        resposta = self.client.patch(
            f"/api/v1/atividades/{atividade.id}/", {"publicada": False}, format="json"
        )

        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.json()["publicada"])
        atividade.refresh_from_db()
        self.assertFalse(atividade.publicada)
        # Despublicada, sai do catálogo anônimo.
        self.client.force_authenticate(user=None)
        self.assertEqual(
            self.client.get(f"/api/v1/atividades/{atividade.id}/").status_code, 404
        )

    def test_atividade_criada_pela_api_nasce_publicada_do_organizador(self):
        """A API não cria rascunho nem proposta: o padrão do model vale."""
        self._autenticar(self.organizador)

        resposta = self.client.post(
            "/api/v1/atividades/", self._dados_atividade(), format="json"
        )

        self.assertEqual(resposta.status_code, 201)
        self.assertTrue(resposta.json()["publicada"])

        # A resposta do POST é o serializer de ESCRITA (o contrato atual, que
        # não mudou); o ciclo se confere na leitura.
        dados = self.client.get(f"/api/v1/atividades/{resposta.json()['id']}/").json()
        self.assertEqual(dados["situacao"], "organizador")
        self.assertTrue(dados["publicada"])
        self.assertIsNone(dados["proponente"])


class InscricaoApiTests(_BaseApiTests):
    """Self-inscrição pela API: reusa a regra da tela (vagas/duplicidade/conflito)."""

    def _atividade(self, titulo="Atividade", hora=8, minuto=0, duracao_min=60, n_vagas=10):
        inicio = datetime(2026, 10, 1, hora, minuto, tzinfo=tz.utc)
        return Atividade.objects.create(
            evento=self.evento, titulo=titulo, descricao="d", local="Sala",
            tipo=self.tipo, data_hora_inicio=inicio,
            data_hora_fim=inicio + timedelta(minutes=duracao_min), n_vagas=n_vagas,
        )

    def _inscrever(self, atividade):
        return self.client.post(
            "/api/v1/minhas-inscricoes/", {"atividade": atividade.id}, format="json"
        )

    @staticmethod
    def _mensagem(resposta):
        """Texto do erro, seja resposta em lista (campo) ou dict (não-campo)."""
        dados = resposta.json()
        if isinstance(dados, dict):
            dados = [item for valores in dados.values() for item in valores]
        return " ".join(str(item) for item in dados)

    def test_inscreve(self):
        atividade = self._atividade()
        self._autenticar(self.participante)

        resposta = self._inscrever(atividade)

        self.assertEqual(resposta.status_code, 201)
        self.assertTrue(
            Inscricao.objects.filter(
                participante=self.participante, atividade=atividade
            ).exists()
        )

    def test_duplicada_recusa(self):
        atividade = self._atividade()
        self._autenticar(self.participante)
        self._inscrever(atividade)

        resposta = self._inscrever(atividade)

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("já está inscrito", self._mensagem(resposta))

    def test_sem_vagas_recusa(self):
        atividade = self._atividade(n_vagas=1)
        outra = U.objects.create_user(
            email="api_outra@example.com", password=SENHA, cpf="39053344705"
        )
        Inscricao.objects.create(participante=outra, atividade=atividade)
        self._autenticar(self.participante)

        resposta = self._inscrever(atividade)

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("vagas", self._mensagem(resposta))

    def test_conflito_de_horario_recusa(self):
        primeira = self._atividade("Primeira", hora=8, duracao_min=60)
        self._atividade("Segunda", hora=8, minuto=30, duracao_min=60)  # sobrepõe
        self._autenticar(self.participante)
        self._inscrever(primeira)

        resposta = self._inscrever(Atividade.objects.get(titulo="Segunda"))

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("Conflito de horário com 'Primeira'", self._mensagem(resposta))

    def test_cancela_a_propria(self):
        atividade = self._atividade()
        self._autenticar(self.participante)
        self._inscrever(atividade)
        inscricao = Inscricao.objects.get(participante=self.participante)

        resposta = self.client.delete(f"/api/v1/minhas-inscricoes/{inscricao.id}/")

        self.assertEqual(resposta.status_code, 204)
        self.assertFalse(Inscricao.objects.filter(pk=inscricao.pk).exists())

    def test_cancelar_bloqueado_por_certificado_emitido(self):
        atividade = self._atividade()
        self._autenticar(self.participante)
        self._inscrever(atividade)
        inscricao = Inscricao.objects.get(participante=self.participante)
        Certificado.objects.create(
            participante=self.participante, atividade=atividade, evento=self.evento
        )

        resposta = self.client.delete(f"/api/v1/minhas-inscricoes/{inscricao.id}/")

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("certificado", resposta.json()["detail"].lower())
        self.assertTrue(Inscricao.objects.filter(pk=inscricao.pk).exists())


class PresencaApiTests(_BaseApiTests):
    """Presença: a organização marca; a própria pessoa confirma pelo QR."""

    def _atividade_agora(self, titulo="Agora"):
        inicio = timezone.now() - timedelta(minutes=10)
        return Atividade.objects.create(
            evento=self.evento, titulo=titulo, descricao="d", local="Sala",
            tipo=self.tipo, data_hora_inicio=inicio,
            data_hora_fim=inicio + timedelta(hours=1), n_vagas=10,
        )

    def _marcar(self, atividade, pessoa, origem="manual"):
        return self.client.post("/api/v1/presencas/", {
            "atividade": atividade.id, "participante": pessoa.id, "origem": origem,
        }, format="json")

    def test_organizacao_marca_e_repetir_e_idempotente(self):
        atividade = self._atividade_agora()
        Inscricao.objects.create(participante=self.participante, atividade=atividade)
        self._autenticar(self.organizador)

        primeira = self._marcar(atividade, self.participante)
        segunda = self._marcar(atividade, self.participante)

        self.assertEqual(primeira.status_code, 201)
        self.assertTrue(primeira.json()["criada"])
        self.assertEqual(segunda.status_code, 200)
        self.assertFalse(segunda.json()["criada"])
        self.assertEqual(Presenca.objects.filter(atividade=atividade).count(), 1)

    def test_quem_nao_organiza_recebe_403(self):
        atividade = self._atividade_agora()
        Inscricao.objects.create(participante=self.participante, atividade=atividade)
        self._autenticar(self.participante)

        resposta = self._marcar(atividade, self.participante)

        self.assertEqual(resposta.status_code, 403)

    def test_equipe_do_evento_pode_marcar(self):
        atividade = self._atividade_agora()
        Inscricao.objects.create(participante=self.participante, atividade=atividade)
        equipe = U.objects.create_user(
            email="equipe_api@example.com", password=SENHA, cpf="39053344705",
            is_equipe=True, is_participante=False,
        )
        self.evento.equipe.add(equipe)
        self._autenticar(equipe)

        resposta = self._marcar(atividade, self.participante)

        self.assertEqual(resposta.status_code, 201)
        self.assertTrue(
            Presenca.objects.filter(
                atividade=atividade, participante=self.participante
            ).exists()
        )

    def test_equipe_de_outro_evento_recebe_403(self):
        atividade = self._atividade_agora()
        Inscricao.objects.create(participante=self.participante, atividade=atividade)
        equipe = U.objects.create_user(
            email="equipe_fora@example.com", password=SENHA, cpf="39053344705",
            is_equipe=True, is_participante=False,
        )
        self._autenticar(equipe)

        resposta = self._marcar(atividade, self.participante)

        self.assertEqual(resposta.status_code, 403)

    def test_pessoa_sem_vinculo_com_o_evento_nao_recebe_presenca(self):
        atividade = self._atividade_agora()
        de_fora = U.objects.create_user(
            email="de_fora@example.com", password=SENHA, cpf="39053344705"
        )
        self._autenticar(self.organizador)

        resposta = self._marcar(atividade, de_fora)

        self.assertEqual(resposta.status_code, 400)
        self.assertIn("vínculo", resposta.json()["detail"])

    def test_pessoa_confirma_pelo_qr_da_atividade(self):
        atividade = self._atividade_agora()
        Inscricao.objects.create(participante=self.participante, atividade=atividade)
        self._autenticar(self.participante)

        resposta = self.client.post("/api/v1/presencas/", {
            "token_atividade": gerar_token_atividade(atividade.id),
        }, format="json")

        self.assertEqual(resposta.status_code, 201)
        self.assertTrue(resposta.json()["criada"])
        self.assertTrue(
            Presenca.objects.filter(
                atividade=atividade, participante=self.participante
            ).exists()
        )

    def test_desfazer_presenca_deixa_auditoria(self):
        atividade = self._atividade_agora()
        presenca = Presenca.objects.create(
            atividade=atividade, participante=self.participante, papel="participante"
        )
        self._autenticar(self.organizador)

        resposta = self.client.delete(f"/api/v1/presencas/{presenca.id}/")

        self.assertEqual(resposta.status_code, 204)
        self.assertFalse(Presenca.objects.filter(pk=presenca.pk).exists())
        self.assertEqual(PresencaCancelada.objects.count(), 1)


class CrachaApiTests(_BaseApiTests):
    """Crachá derivado (lista, QR em PNG) e o PDF do evento."""

    def setUp(self):
        super().setUp()
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Oficina", descricao="d", local="Sala",
            tipo=self.tipo, data_hora_inicio=timezone.now(),
            data_hora_fim=timezone.now() + timedelta(hours=1), n_vagas=10,
        )
        Inscricao.objects.create(participante=self.participante, atividade=self.atividade)

    def test_lista_o_cracha_com_token_e_url(self):
        self._autenticar(self.participante)

        crachas = self.client.get("/api/v1/meus-crachas/").json()

        self.assertEqual(len(crachas), 1)
        cracha = crachas[0]
        self.assertEqual(cracha["evento_id"], self.evento.id)
        self.assertEqual(cracha["papel"], "participante")
        self.assertTrue(cracha["token"])
        # O QR abre o link curto público `/c/<token>`; o MESMO token é aceito
        # pela rota de verificação da API (coberto em VerificacaoApiTests).
        self.assertIn(cracha["token"], cracha["url"])
        self.assertIn("qr.png", cracha["qr_png"])

    def test_qr_do_cracha_em_png(self):
        self._autenticar(self.participante)

        resposta = self.client.get(f"/api/v1/meus-crachas/{self.evento.id}/qr.png")

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "image/png")

    def test_cracha_de_evento_sem_papel_da_404(self):
        outro = Evento.objects.create(
            title="Outro evento", description="d", local="Sala",
            data_inicio=date(2026, 11, 1), data_fim=date(2026, 11, 2),
            categoria="formacao", organizador=self.organizador,
        )
        self._autenticar(self.participante)

        resposta = self.client.get(f"/api/v1/meus-crachas/{outro.id}/qr.png")

        self.assertEqual(resposta.status_code, 404)

    def test_pdf_dos_crachas_e_do_organizador(self):
        self._autenticar(self.organizador)

        resposta = self.client.get(f"/api/v1/eventos/{self.evento.id}/crachas.pdf")

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta["Content-Type"], "application/pdf")

    def test_pdf_dos_crachas_recusa_quem_nao_organiza(self):
        self._autenticar(self.participante)

        resposta = self.client.get(f"/api/v1/eventos/{self.evento.id}/crachas.pdf")

        self.assertEqual(resposta.status_code, 403)


class QrAtividadeApiTests(_BaseApiTests):
    """QR de presença da atividade: organizador (ou palestrante) busca a imagem."""

    def setUp(self):
        super().setUp()
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Oficina", descricao="d", local="Sala",
            tipo=self.tipo, data_hora_inicio=timezone.now(),
            data_hora_fim=timezone.now() + timedelta(hours=1), n_vagas=10,
        )

    def test_organizador_pega_o_qr_em_json_e_png(self):
        self._autenticar(self.organizador)

        dados = self.client.get(f"/api/v1/atividades/{self.atividade.id}/qrcode/")

        self.assertEqual(dados.status_code, 200)
        self.assertIn("url", dados.json())
        self.assertTrue(dados.json()["png"].startswith("data:image"))

        png = self.client.get(f"/api/v1/atividades/{self.atividade.id}/qrcode.png")
        self.assertEqual(png.status_code, 200)
        self.assertEqual(png["Content-Type"], "image/png")

    def test_quem_nao_organiza_nem_palestra_recebe_403(self):
        self._autenticar(self.participante)

        resposta = self.client.get(f"/api/v1/atividades/{self.atividade.id}/qrcode/")

        self.assertEqual(resposta.status_code, 403)


class VerificacaoApiTests(_BaseApiTests):
    """Verificação pública do token do crachá."""

    def setUp(self):
        super().setUp()
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Oficina", descricao="d", local="Sala",
            tipo=self.tipo, data_hora_inicio=timezone.now(),
            data_hora_fim=timezone.now() + timedelta(hours=1), n_vagas=10,
        )
        Inscricao.objects.create(participante=self.participante, atividade=self.atividade)

    def test_token_valido_responde_sem_dado_pessoal(self):
        self._autenticar(self.participante)
        token = self.client.get("/api/v1/meus-crachas/").json()[0]["token"]
        self.client.force_authenticate(user=None)   # portaria confere deslogada

        resposta = self.client.get(f"/api/v1/verificar/{token}/")

        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertTrue(dados["valido"])
        self.assertEqual(dados["papel"], "participante")
        self.assertEqual(dados["evento_id"], self.evento.id)
        self.assertNotIn("cpf", dados)
        self.assertNotIn("email", dados)

    def test_token_invalido_responde_falso(self):
        resposta = self.client.get("/api/v1/verificar/isto-nao-e-um-token/")

        self.assertGreaterEqual(resposta.status_code, 400)
        self.assertFalse(resposta.json()["valido"])


class PermissoesEscritaApiTests(_BaseApiTests):
    """Quem pode escrever: só organizador, e só nos próprios eventos."""

    def _dados_evento(self):
        return {
            "title": "Evento novo", "description": "d", "local": "Sala",
            "data_inicio": "2026-11-01", "data_fim": "2026-11-02",
        }

    def test_anonimo_nao_cria_evento(self):
        resposta = self.client.post("/api/v1/eventos/", self._dados_evento(), format="json")

        self.assertIn(resposta.status_code, (401, 403))

    def test_participante_nao_cria_evento(self):
        self._autenticar(self.participante)

        resposta = self.client.post("/api/v1/eventos/", self._dados_evento(), format="json")

        self.assertEqual(resposta.status_code, 403)

    def test_organizador_nao_edita_evento_alheio(self):
        outro = U.objects.create_user(
            email="outro_org@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        alheio = Evento.objects.create(
            title="Alheio", description="d", local="Sala",
            data_inicio=date(2026, 11, 1), data_fim=date(2026, 11, 2),
            categoria="formacao", organizador=outro,
        )
        self._autenticar(self.organizador)

        resposta = self.client.patch(
            f"/api/v1/eventos/{alheio.id}/", {"title": "Invadido"}, format="json"
        )

        self.assertEqual(resposta.status_code, 403)
        alheio.refresh_from_db()
        self.assertEqual(alheio.title, "Alheio")

    def test_dono_edita_o_proprio_evento(self):
        self._autenticar(self.organizador)

        resposta = self.client.patch(
            f"/api/v1/eventos/{self.evento.id}/", {"title": "Renomeado"}, format="json"
        )

        self.assertEqual(resposta.status_code, 200)
        self.evento.refresh_from_db()
        self.assertEqual(self.evento.title, "Renomeado")


class AuthApiTests(_BaseApiTests):
    """Token por e-mail+senha e cadastro de participante pela API."""

    def test_token_com_credenciais(self):
        resposta = self.client.post("/api/v1/auth/token/", {
            "email": "api_org@example.com", "password": SENHA,
        }, format="json")

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()["token"])
        self.assertEqual(resposta.json()["user_id"], self.organizador.pk)

    def test_token_com_senha_errada(self):
        resposta = self.client.post("/api/v1/auth/token/", {
            "email": "api_org@example.com", "password": "senha-errada",
        }, format="json")

        self.assertEqual(resposta.status_code, 400)

    def test_registro_cria_participante(self):
        resposta = self.client.post("/api/v1/auth/registro/", {
            "email": "novo_api@example.com", "password": SENHA,
            "cpf": "11144477735", "first_name": "Novo",
        }, format="json")

        self.assertEqual(resposta.status_code, 201)
        self.assertTrue(resposta.json()["token"])
        novo = U.objects.get(email="novo_api@example.com")
        self.assertTrue(novo.is_participante)
        self.assertFalse(novo.is_organizador)

    def test_registro_recusa_email_repetido(self):
        resposta = self.client.post("/api/v1/auth/registro/", {
            "email": "api_org@example.com", "password": SENHA, "cpf": "11144477735",
        }, format="json")

        self.assertEqual(resposta.status_code, 400)
