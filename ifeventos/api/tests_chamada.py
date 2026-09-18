"""Testes da API da chamada de proposições (F2).

Exercitam o que a tela já fazia, mas pela porta da API: janela da chamada,
catálogo de espaços, grade de vagas (inclusive em lote) e o ciclo da proposta
(propor → editar/cancelar → aprovar/rejeitar). O ponto central é que a API NÃO
reimplementa regra: tudo passa por `eventos.propostas`, então as mensagens de
erro e as travas são as mesmas da tela.
"""

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from eventos.models import (
    Atividade,
    ChamadaProposicoes,
    Espaco,
    Evento,
    TipoAtividade,
    Vaga,
)

U = get_user_model()
SENHA = "SenhaForte123!"


class _BaseChamadaApiTests(TestCase):
    """Cenário comum: organizador dono, dois participantes, evento com chamada."""

    def setUp(self):
        self.organizador = U.objects.create_user(
            email="chamada_org@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True, is_participante=False,
        )
        self.outro_organizador = U.objects.create_user(
            email="chamada_org2@example.com", password=SENHA, cpf="98765432100",
            is_organizador=True, is_participante=False,
        )
        self.participante = U.objects.create_user(
            email="chamada_part@example.com", password=SENHA, cpf="11144477735",
        )
        self.colega = U.objects.create_user(
            email="chamada_part2@example.com", password=SENHA, cpf="39053344705",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")

        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento da Chamada", description="d", local="Auditório",
            data_inicio=hoje + timedelta(days=10),
            data_fim=hoje + timedelta(days=12),
            categoria="formacao", organizador=self.organizador,
        )
        agora = timezone.now()
        self.chamada = ChamadaProposicoes.objects.create(
            evento=self.evento, titulo="Chamada de propostas",
            inicio=agora - timedelta(days=1), fim=agora + timedelta(days=5),
            aberta=True,
        )
        self.espaco = Espaco.objects.create(nome="Auditório", capacidade=40)
        self.sala = Espaco.objects.create(nome="Sala 1", capacidade=20)
        self.vaga = Vaga.objects.create(
            evento=self.evento, espaco=self.espaco,
            inicio=self._quando(14), fim=self._quando(16),
        )
        # Segunda vaga: dois proponentes não podem ocupar a mesma janela.
        self.vaga2 = Vaga.objects.create(
            evento=self.evento, espaco=self.sala,
            inicio=self._quando(14), fim=self._quando(16),
        )
        self.client = APIClient()

    def _quando(self, hora, dia=10):
        """Data/hora aware dentro do período do evento (padrão: primeiro dia)."""
        dia_base = timezone.localdate() + timedelta(days=dia)
        return timezone.make_aware(datetime.combine(dia_base, time(hora, 0)))

    def _autenticar(self, usuario):
        self.client.force_authenticate(user=usuario)

    def _proposta(self, vaga=None, **extra):
        dados = {
            "vaga": (vaga or self.vaga).pk,
            "titulo": "Minha oficina",
            "descricao": "Descrição",
            "tipo": self.tipo.pk,
        }
        dados.update(extra)
        return self.client.post("/api/v1/propostas/", dados, format="json")


class ChamadaApiTests(_BaseChamadaApiTests):
    def test_organizador_le_a_janela_e_o_que_esta_livre(self):
        self._autenticar(self.organizador)
        resposta = self.client.get(f"/api/v1/eventos/{self.evento.pk}/chamada/")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertTrue(resposta.data["aberta_agora"])
        self.assertEqual(len(resposta.data["vagas_livres"]), 2)
        self.assertEqual(resposta.data["vagas_livres"][0]["espaco"], "Auditório")

    def test_organizador_abre_e_encerra_a_chamada(self):
        self.chamada.aberta = False
        self.chamada.save(update_fields=["aberta"])
        self._autenticar(self.organizador)

        url = f"/api/v1/eventos/{self.evento.pk}/chamada/"
        resposta = self.client.put(url, {"aberta": True}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertTrue(resposta.data["aberta_agora"])

        resposta = self.client.put(url, {"aberta": False}, format="json")
        self.assertFalse(resposta.data["aberta_agora"])

    def test_chamada_cria_a_janela_quando_ainda_nao_existe(self):
        chamada_antiga = self.chamada
        evento = Evento.objects.create(
            title="Sem chamada", description="d", local="Sala",
            data_inicio=timezone.localdate(), data_fim=timezone.localdate(),
            categoria="formacao", organizador=self.organizador,
        )
        self.assertFalse(ChamadaProposicoes.objects.filter(evento=evento).exists())

        self._autenticar(self.organizador)
        url = f"/api/v1/eventos/{evento.pk}/chamada/"
        inicio, fim = chamada_antiga.inicio, chamada_antiga.fim
        resposta = self.client.put(
            url,
            {"inicio": inicio.isoformat(), "fim": fim.isoformat(), "aberta": True},
            format="json",
        )
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertTrue(ChamadaProposicoes.objects.filter(evento=evento).exists())

    def test_chamada_inexistente_responde_404(self):
        evento = Evento.objects.create(
            title="Sem chamada", description="d", local="Sala",
            data_inicio=timezone.localdate(), data_fim=timezone.localdate(),
            categoria="formacao", organizador=self.organizador,
        )
        self._autenticar(self.participante)
        resposta = self.client.get(f"/api/v1/eventos/{evento.pk}/chamada/")
        self.assertEqual(resposta.status_code, 404)

    def test_participante_le_mas_nao_edita_a_janela(self):
        self._autenticar(self.participante)
        url = f"/api/v1/eventos/{self.evento.pk}/chamada/"
        self.assertEqual(self.client.get(url).status_code, 200)

        resposta = self.client.put(url, {"aberta": False}, format="json")
        self.assertEqual(resposta.status_code, 403)
        self.chamada.refresh_from_db()
        self.assertTrue(self.chamada.aberta)

    def test_outro_organizador_nao_edita_a_janela(self):
        self._autenticar(self.outro_organizador)
        resposta = self.client.put(
            f"/api/v1/eventos/{self.evento.pk}/chamada/", {"aberta": False},
            format="json",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_anonimo_nao_le_a_janela(self):
        resposta = self.client.get(f"/api/v1/eventos/{self.evento.pk}/chamada/")
        self.assertEqual(resposta.status_code, 403)

    def test_painel_exige_organizador(self):
        self._autenticar(self.organizador)
        resposta = self.client.get(
            f"/api/v1/eventos/{self.evento.pk}/painel-chamada/"
        )
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertIn("kpis", resposta.data)
        self.assertIn("vagas_livres", resposta.data)

        self._autenticar(self.participante)
        resposta = self.client.get(
            f"/api/v1/eventos/{self.evento.pk}/painel-chamada/"
        )
        self.assertEqual(resposta.status_code, 403)


class EspacoApiTests(_BaseChamadaApiTests):
    def test_leitura_do_catalogo_e_publica(self):
        resposta = self.client.get("/api/v1/espacos/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["count"], 2)

    def test_organizador_cria_espaco(self):
        self._autenticar(self.organizador)
        resposta = self.client.post(
            "/api/v1/espacos/", {"nome": "Quadra", "capacidade": 60}, format="json"
        )
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["nome"], "Quadra")

    def test_espaco_de_nome_repetido_recusa(self):
        self._autenticar(self.organizador)
        resposta = self.client.post(
            "/api/v1/espacos/", {"nome": "Auditório"}, format="json"
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("nome", resposta.data)

    def test_participante_nao_cria_espaco(self):
        self._autenticar(self.participante)
        resposta = self.client.post(
            "/api/v1/espacos/", {"nome": "Quadra"}, format="json"
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(Espaco.objects.filter(nome="Quadra").exists())


class VagaApiTests(_BaseChamadaApiTests):
    def test_organizador_cria_vaga_na_grade(self):
        self._autenticar(self.organizador)
        resposta = self.client.post(
            "/api/v1/vagas/",
            {
                "evento": self.evento.pk, "espaco": self.sala.pk,
                "inicio": self._quando(10).isoformat(),
                "fim": self._quando(12).isoformat(),
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertTrue(resposta.data["livre"])
        self.assertEqual(resposta.data["ocupadas"], 0)

    def test_vaga_fora_do_periodo_do_evento_recusa(self):
        self._autenticar(self.organizador)
        resposta = self.client.post(
            "/api/v1/vagas/",
            {
                "evento": self.evento.pk, "espaco": self.sala.pk,
                "inicio": self._quando(10, dia=1).isoformat(),
                "fim": self._quando(12, dia=1).isoformat(),
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("inicio", resposta.data)

    def test_vaga_repetida_recusa(self):
        self._autenticar(self.organizador)
        resposta = self.client.post(
            "/api/v1/vagas/",
            {
                "evento": self.evento.pk, "espaco": self.espaco.pk,
                "inicio": self.vaga.inicio.isoformat(),
                "fim": self.vaga.fim.isoformat(),
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertEqual(Vaga.objects.count(), 2)

    def test_vaga_com_proposta_trava_espaco_e_horario(self):
        self._autenticar(self.participante)
        self.assertEqual(self._proposta().status_code, 201)

        self._autenticar(self.organizador)
        url = f"/api/v1/vagas/{self.vaga.pk}/"
        resposta = self.client.patch(url, {"espaco": self.sala.pk}, format="json")
        self.assertEqual(resposta.status_code, 400)

        resposta = self.client.patch(
            url, {"capacidade": 3}, format="json"
        )
        self.assertEqual(resposta.status_code, 200, resposta.data)

    def test_participante_le_a_grade_mas_nao_cria(self):
        self._autenticar(self.participante)
        resposta = self.client.get(f"/api/v1/vagas/?evento={self.evento.pk}")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["count"], 2)

        resposta = self.client.post(
            "/api/v1/vagas/",
            {
                "evento": self.evento.pk, "espaco": self.sala.pk,
                "inicio": self._quando(10).isoformat(),
                "fim": self._quando(12).isoformat(),
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_gerar_grade_em_lote_e_idempotente(self):
        self._autenticar(self.organizador)
        url = f"/api/v1/eventos/{self.evento.pk}/vagas/gerar/"
        dados = {
            "dias": [(timezone.localdate() + timedelta(days=10)).isoformat()],
            "blocos": ["08:00-10:00", "10:00-12:00"],
            "espacos": [self.espaco.pk, self.sala.pk],
        }
        resposta = self.client.post(url, dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data, {"criadas": 4, "existentes": 0})

        resposta = self.client.post(url, dados, format="json")
        self.assertEqual(resposta.data, {"criadas": 0, "existentes": 4})
        self.assertEqual(Vaga.objects.count(), 6)  # 4 + as 2 vagas do setUp

    def test_gerar_grade_recusa_dia_fora_do_evento_e_bloco_invalido(self):
        self._autenticar(self.organizador)
        url = f"/api/v1/eventos/{self.evento.pk}/vagas/gerar/"
        resposta = self.client.post(
            url,
            {
                "dias": [(timezone.localdate() + timedelta(days=1)).isoformat()],
                "blocos": ["08:00-10:00"], "espacos": [self.sala.pk],
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("dias", resposta.data)

        resposta = self.client.post(
            url,
            {
                "dias": [(timezone.localdate() + timedelta(days=10)).isoformat()],
                "blocos": ["oito da manhã"], "espacos": [self.sala.pk],
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("blocos", resposta.data)


class PropostaApiTests(_BaseChamadaApiTests):
    def test_participante_propoe_e_a_vaga_fica_ocupada(self):
        self._autenticar(self.participante)
        resposta = self._proposta()
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["situacao"], Atividade.SITUACAO_PENDENTE)
        self.assertFalse(resposta.data["publicada"])
        self.assertEqual(resposta.data["vaga"]["id"], self.vaga.pk)
        self.assertEqual(resposta.data["vaga"]["ocupadas"], 1)
        self.assertEqual(resposta.data["vaga"]["vagas_restantes"], 0)

    def test_anonimo_nao_propoe(self):
        resposta = self._proposta()
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(Atividade.objects.filter(proponente__isnull=False).count(), 0)

    def test_propor_com_chamada_encerrada_recusa(self):
        self.chamada.aberta = False
        self.chamada.save(update_fields=["aberta"])
        self._autenticar(self.participante)
        resposta = self._proposta()
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("detail", resposta.data)
        self.assertEqual(Atividade.objects.filter(proponente__isnull=False).count(), 0)

    def test_propor_em_vaga_ja_ocupada_recusa(self):
        self._autenticar(self.participante)
        self.assertEqual(self._proposta().status_code, 201)

        self._autenticar(self.colega)
        resposta = self._proposta()
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("vaga", resposta.data)

    def test_propor_sem_tipo_recusa(self):
        self._autenticar(self.participante)
        resposta = self._proposta(tipo=None)
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("tipo", resposta.data)

    def test_participante_so_ve_as_proprias_e_nao_acessa_a_do_colega(self):
        self._autenticar(self.colega)
        da_colega = self._proposta(vaga=self.vaga2, titulo="Do colega")
        self.assertEqual(da_colega.status_code, 201)

        self._autenticar(self.participante)
        self.assertEqual(self._proposta().status_code, 201)

        lista = self.client.get("/api/v1/propostas/")
        self.assertEqual(lista.data["count"], 1)
        self.assertEqual(lista.data["results"][0]["titulo"], "Minha oficina")

        detalhe = self.client.get(f"/api/v1/propostas/{da_colega.data['id']}/")
        self.assertEqual(detalhe.status_code, 404)

    def test_organizador_ve_todas_e_filtra(self):
        self._autenticar(self.participante)
        self.assertEqual(self._proposta().status_code, 201)
        self._autenticar(self.colega)
        self.assertEqual(
            self._proposta(vaga=self.vaga2, titulo="Do colega").status_code, 201
        )

        self._autenticar(self.organizador)
        lista = self.client.get(f"/api/v1/propostas/?evento={self.evento.pk}")
        self.assertEqual(lista.data["count"], 2)

        pendentes = self.client.get(
            f"/api/v1/propostas/?evento={self.evento.pk}&situacao=pendente"
        )
        self.assertEqual(pendentes.data["count"], 2)

        minhas = self.client.get(f"/api/v1/propostas/?minhas=1")
        self.assertEqual(minhas.data["count"], 0)

    def test_autor_edita_enquanto_pendente_e_perde_o_direito_apos_a_decisao(self):
        self._autenticar(self.participante)
        proposta = self._proposta().data
        url = f"/api/v1/propostas/{proposta['id']}/"

        resposta = self.client.patch(url, {"titulo": "Novo título"}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["titulo"], "Novo título")

        self._autenticar(self.organizador)
        self.assertEqual(self.client.post(f"{url}aprovar/", {}, format="json").status_code, 200)

        self._autenticar(self.participante)
        resposta = self.client.patch(url, {"titulo": "De novo"}, format="json")
        self.assertEqual(resposta.status_code, 400)

    def test_terceiro_nao_edita_a_proposta_do_autor(self):
        self._autenticar(self.participante)
        proposta = self._proposta().data

        self._autenticar(self.colega)
        resposta = self.client.patch(
            f"/api/v1/propostas/{proposta['id']}/", {"titulo": "Invadindo"},
            format="json",
        )
        self.assertEqual(resposta.status_code, 404)

    def test_autor_cancela_a_propria_proposta_e_libera_a_vaga(self):
        self._autenticar(self.participante)
        proposta = self._proposta().data

        self._autenticar(self.colega)
        self.assertEqual(
            self.client.delete(f"/api/v1/propostas/{proposta['id']}/").status_code,
            404,
        )

        self._autenticar(self.participante)
        resposta = self.client.delete(f"/api/v1/propostas/{proposta['id']}/")
        self.assertEqual(resposta.status_code, 204)
        self.assertFalse(Atividade.objects.filter(pk=proposta["id"]).exists())

        self._autenticar(self.colega)
        self.assertEqual(self._proposta().status_code, 201)

    def test_organizador_remove_a_proposta_pendente_ou_decidida(self):
        self._autenticar(self.participante)
        pendente = self._proposta().data

        # Pendente: o organizador remove direto (equivale a excluir a atividade).
        self._autenticar(self.organizador)
        resposta = self.client.delete(f"/api/v1/propostas/{pendente['id']}/")
        self.assertEqual(resposta.status_code, 204)
        self.assertFalse(Atividade.objects.filter(pk=pendente["id"]).exists())

        # Decidida: o autor já não cancela (400), mas o organizador remove.
        self._autenticar(self.colega)
        decidida = self._proposta(vaga=self.vaga2).data
        self._autenticar(self.organizador)
        self.assertEqual(
            self.client.post(
                f"/api/v1/propostas/{decidida['id']}/aprovar/", {}, format="json"
            ).status_code,
            200,
        )

        self._autenticar(self.colega)
        resposta = self.client.delete(f"/api/v1/propostas/{decidida['id']}/")
        self.assertEqual(resposta.status_code, 400)

        self._autenticar(self.organizador)
        resposta = self.client.delete(f"/api/v1/propostas/{decidida['id']}/")
        self.assertEqual(resposta.status_code, 204)
        self.assertFalse(Atividade.objects.filter(pk=decidida["id"]).exists())
        self.assertTrue(Vaga.objects.get(pk=self.vaga2.pk).livre)

    def test_aprovacao_publica_e_so_para_organizador(self):
        self._autenticar(self.participante)
        proposta = self._proposta().data
        url = f"/api/v1/propostas/{proposta['id']}/aprovar/"

        # Participante não decide (nem o dono da proposta).
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 403)

        # Espelha o site (`pode_gerenciar_evento`): qualquer organizador decide.
        self._autenticar(self.outro_organizador)
        resposta = self.client.post(url, {}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["situacao"], Atividade.SITUACAO_APROVADA)
        self.assertTrue(resposta.data["publicada"])

        # Decidida, não se decide de novo.
        self._autenticar(self.organizador)
        self.assertEqual(self.client.post(url, {}, format="json").status_code, 400)

    def test_aprovacao_sem_publicar(self):
        self._autenticar(self.participante)
        proposta = self._proposta().data

        self._autenticar(self.organizador)
        resposta = self.client.post(
            f"/api/v1/propostas/{proposta['id']}/aprovar/", {"publicar": False},
            format="json",
        )
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["situacao"], Atividade.SITUACAO_APROVADA)
        self.assertFalse(resposta.data["publicada"])

    def test_rejeicao_exige_motivo_e_libera_a_vaga(self):
        self._autenticar(self.participante)
        proposta = self._proposta().data
        url = f"/api/v1/propostas/{proposta['id']}/rejeitar/"

        self._autenticar(self.organizador)
        resposta = self.client.post(url, {}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("motivo", resposta.data)

        resposta = self.client.post(url, {"motivo": "Fora do tema"}, format="json")
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["situacao"], Atividade.SITUACAO_REJEITADA)
        self.assertEqual(resposta.data["motivo_rejeicao"], "Fora do tema")
        self.assertEqual(resposta.data["vaga"]["ocupadas"], 0)
        self.assertEqual(resposta.data["vaga"]["vagas_restantes"], 1)

    def test_decisao_e_terminal(self):
        self._autenticar(self.participante)
        proposta = self._proposta().data
        aprovar = f"/api/v1/propostas/{proposta['id']}/aprovar/"
        rejeitar = f"/api/v1/propostas/{proposta['id']}/rejeitar/"

        self._autenticar(self.organizador)
        self.assertEqual(self.client.post(aprovar, {}, format="json").status_code, 200)

        # Rejeitar o que já foi aprovado trocaria o estado em silêncio.
        resposta = self.client.post(rejeitar, {"motivo": "Mudei"}, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("detail", resposta.data)
        self.assertEqual(
            self.client.get(f"/api/v1/propostas/{proposta['id']}/").data["situacao"],
            Atividade.SITUACAO_APROVADA,
        )

    def test_atividade_criada_com_vaga_assume_a_janela_e_ocupa_a_vaga(self):
        self._autenticar(self.organizador)
        resposta = self.client.post(
            "/api/v1/atividades/",
            {
                "evento": self.evento.pk, "titulo": "Mesa redonda",
                "descricao": "d", "tipo": self.tipo.pk, "n_vagas": 30,
                "vaga": self.vaga.pk,
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 201, resposta.data)
        atividade = Atividade.objects.get(pk=resposta.data["id"])
        self.assertEqual(atividade.local, self.espaco.nome)
        self.assertEqual(atividade.data_hora_inicio, self.vaga.inicio)
        self.assertEqual(atividade.data_hora_fim, self.vaga.fim)

        grade = self.client.get(f"/api/v1/vagas/{self.vaga.pk}/")
        self.assertFalse(grade.data["livre"])
        self.assertEqual(grade.data["ocupadas"], 1)

        # Sem vaga, local e horário continuam obrigatórios (como no site).
        resposta = self.client.post(
            "/api/v1/atividades/",
            {
                "evento": self.evento.pk, "titulo": "Sem horário",
                "descricao": "d", "tipo": self.tipo.pk, "n_vagas": 10,
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("local", resposta.data)
