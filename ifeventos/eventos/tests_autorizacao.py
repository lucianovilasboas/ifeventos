"""Autorização das rotas do organizador.

Regra do sistema (`pode_gerenciar_evento`): quem tem a flag de organizador
opera qualquer evento; participante/equipe levam 403. As ações globais
(criar evento, palestrante, tipo, espaço, modelo CSV) exigem is_organizador.
"""

from datetime import date, datetime, timezone as tz

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from eventos.models import Atividade, Evento, Inscricao, TipoAtividade

U = get_user_model()
SENHA = "SenhaForte123!"


def _novo_usuario(email, **flags):
    base = {"email": email, "password": SENHA, "cpf": ""}
    base.update(flags)
    return U.objects.create_user(**base)


class _BaseAutorizacao(TestCase):
    def setUp(self):
        self.org = _novo_usuario("org_auth@example.com", cpf="12345678909", is_organizador=True)
        self.outro_org = _novo_usuario(
            "org2_auth@example.com", cpf="52998224725", is_organizador=True
        )
        self.participante = _novo_usuario("part_auth@example.com", cpf="11144477735")
        self.equipe = _novo_usuario("equipe_auth@example.com", cpf="39053344705", is_equipe=True)
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.evento = Evento.objects.create(
            title="Evento Auth", description="d", local="Auditório",
            data_inicio=date(2026, 10, 10), data_fim=date(2026, 10, 12),
            organizador=self.org,
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Palestra A", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 10, 11, 0, tzinfo=tz.utc),
            n_vagas=10,
        )


class AtividadesDoEventoTests(_BaseAutorizacao):
    def test_participante_nao_abre_a_pagina_de_gestao(self):
        self.client.force_login(self.participante)
        resposta = self.client.get(
            reverse("organizador:atividades_evento", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 403)

    def test_equipe_nao_abre_a_pagina_de_gestao(self):
        self.client.force_login(self.equipe)
        resposta = self.client.get(
            reverse("organizador:atividades_evento", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 403)

    def test_organizador_abre_a_pagina_de_gestao(self):
        self.client.force_login(self.org)
        resposta = self.client.get(
            reverse("organizador:atividades_evento", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 200)


class PublicarExcluirTests(_BaseAutorizacao):
    def test_participante_nao_publica(self):
        self.client.force_login(self.participante)
        resposta = self.client.post(
            reverse("organizador:publicar_atividade", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 403)
        self.atividade.refresh_from_db()
        self.assertTrue(self.atividade.publicada)

    def test_participante_nao_exclui(self):
        self.client.force_login(self.participante)
        resposta = self.client.post(
            reverse("organizador:excluir_atividade", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 403)
        self.assertTrue(Atividade.objects.filter(id=self.atividade.id).exists())

    def test_equipe_nao_publica(self):
        self.client.force_login(self.equipe)
        resposta = self.client.post(
            reverse("organizador:publicar_atividade", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 403)

    def test_qualquer_organizador_publica(self):
        # Regra do sistema: a flag de organizador permite operar qualquer evento.
        self.client.force_login(self.outro_org)
        resposta = self.client.post(
            reverse("organizador:publicar_atividade", args=[self.atividade.id])
        )
        self.assertEqual(resposta.status_code, 302)
        self.atividade.refresh_from_db()
        self.assertFalse(self.atividade.publicada)


class CriarEditarAtividadeTests(_BaseAutorizacao):
    def test_participante_nao_cria_edita_em_evento_alheio(self):
        self.client.force_login(self.participante)
        for url in [
            reverse("organizador:criar_editar_atividade_criar", args=[self.evento.id]),
            reverse("organizador:criar_editar_atividade_editar",
                    args=[self.evento.id, self.atividade.id]),
            reverse("organizador:editar_atividade", args=[self.atividade.id]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        # POST também é recusado.
        self.assertEqual(
            self.client.post(
                reverse("organizador:criar_editar_atividade_criar", args=[self.evento.id]),
            ).status_code,
            403,
        )

    def test_participante_nao_cria_atividade_pelo_modal(self):
        self.client.force_login(self.participante)
        resposta = self.client.post(reverse("organizador:criar_atividade"), {"evento": self.evento.id})
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(self.evento.atividades.count(), 1)


class AcoesGlobaisTests(_BaseAutorizacao):
    def test_participante_nao_cria_evento(self):
        self.client.force_login(self.participante)
        resposta = self.client.post(reverse("organizador:criar_evento"), {
            "title": "Invadido", "description": "d", "local": "l",
            "data_inicio": "2026-11-01", "data_fim": "2026-11-02",
        })
        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(Evento.objects.filter(title="Invadido").exists())

    def test_participante_nao_cria_palestrante_tipo_espaco(self):
        self.client.force_login(self.participante)
        for url, dados in [
            (reverse("organizador:adicionar_palestrante"), {"email": "p@example.com"}),
            (reverse("organizador:adicionar_tipo_atividade"), {"nome": "X"}),
            (reverse("organizador:adicionar_espaco_ajax"), {"local-nome": "Sala"}),
        ]:
            resposta = self.client.post(url, dados)
            self.assertEqual(resposta.status_code, 403, url)

    def test_participante_nao_baixa_modelo_csv(self):
        self.client.force_login(self.participante)
        resposta = self.client.get(reverse("organizador:modelo_metadados_csv"))
        self.assertEqual(resposta.status_code, 302)  # redirect para o painel


class CertificadosTests(_BaseAutorizacao):
    def setUp(self):
        super().setUp()
        self.inscricao = Inscricao.objects.create(
            participante=self.participante, atividade=self.atividade
        )

    def test_participante_nao_emite_certificado(self):
        self.client.force_login(self.participante)
        resposta = self.client.post(
            reverse("organizador:emitir_certificado_inscricao", args=[self.inscricao.id])
        )
        self.assertEqual(resposta.status_code, 403)

    def test_organizador_emite_certificado(self):
        self.inscricao.certificado_emitido = True
        self.inscricao.save()
        self.client.force_login(self.org)
        resposta = self.client.post(
            reverse("organizador:emitir_certificado_inscricao", args=[self.inscricao.id])
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.json()["certificado"])

    def test_participante_nao_emite_certificados_do_evento(self):
        self.client.force_login(self.participante)
        resposta = self.client.post(
            reverse("organizador:emitir_certificados_evento", args=[self.evento.id])
        )
        self.assertEqual(resposta.status_code, 403)


class IATests(_BaseAutorizacao):
    def test_participante_nao_usa_a_ia(self):
        self.client.force_login(self.participante)
        for url in [
            reverse("organizador:gerar_descricao"),
            reverse("organizador:sugerir_categoria"),
            reverse("organizador:ia_mensagem"),
        ]:
            resposta = self.client.post(url, data="{}", content_type="application/json")
            self.assertEqual(resposta.status_code, 403, url)

    def test_organizador_passa_o_portao_da_ia(self):
        # Sem título a view responde 400 (e não 403): prova que o organizador
        # passou da checagem de papel.
        self.client.force_login(self.org)
        resposta = self.client.post(
            reverse("organizador:sugerir_categoria"),
            data='{"titulo": ""}', content_type="application/json",
        )
        self.assertEqual(resposta.status_code, 400)