"""Testes da chamada de proposições de atividades.

Cobrem as regras (janela, reserva de vaga, conflitos de espaço/palestrante,
aprovação/rejeição/cancelamento), a invisibilidade pública das propostas
(programação e API) e as telas do proponente e do organizador.
"""

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from eventos import propostas
from eventos.models import Atividade, ChamadaProposicoes, Espaco, Evento, TipoAtividade, Vaga
from eventos.propostas import PropostaBloqueada
from eventos.services import sugerir_tipo_por_palavras

U = get_user_model()
SENHA = "SenhaForte123!"


class BasePropostasTests(TestCase):
    """Evento futuro com chamada aberta, um espaço e uma vaga de 14h às 16h."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_prop@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.pessoa = U.objects.create_user(
            email="pessoa_prop@example.com", password=SENHA, cpf="11144477735",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")

        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento das Propostas", description="d", local="Campus",
            data_inicio=hoje + timedelta(days=10),
            data_fim=hoje + timedelta(days=12),
            categoria="formacao", organizador=self.org,
        )
        agora = timezone.now()
        self.chamada = ChamadaProposicoes.objects.create(
            evento=self.evento, titulo="Chamada de propostas",
            inicio=agora - timedelta(days=1), fim=agora + timedelta(days=5),
            aberta=True,
        )
        # O espaço é do catálogo da escola (não do evento): o mesmo pode ser
        # usado por vários eventos, em grades diferentes.
        self.espaco = Espaco.objects.create(nome="Auditório", capacidade=40)

        dia = self.evento.data_inicio
        self.inicio = timezone.make_aware(datetime.combine(dia, time(14, 0)))
        self.fim = timezone.make_aware(datetime.combine(dia, time(16, 0)))
        self.vaga = self._vaga(self.inicio, self.fim)

    def _vaga(self, inicio, fim, capacidade=1, espaco=None):
        return Vaga.objects.create(
            evento=self.evento, espaco=espaco or self.espaco,
            inicio=inicio, fim=fim, capacidade=capacidade,
        )

    def _propor(self, **extra):
        dados = {
            "vaga": self.vaga, "titulo": "Minha proposta", "descricao": "d",
            "tipo": self.tipo,
        }
        dados.update(extra)
        return propostas.propor(self.pessoa, self.evento, **dados)


class RegrasPropostaTests(BasePropostasTests):
    def test_propor_cria_rascunho_pendente_e_reserva_a_vaga(self):
        proposta = self._propor()

        self.assertFalse(proposta.publicada)
        self.assertEqual(proposta.situacao, Atividade.SITUACAO_PENDENTE)
        self.assertEqual(proposta.proponente, self.pessoa)
        self.assertEqual(proposta.vaga, self.vaga)
        self.assertEqual(proposta.local, "Auditório")
        self.assertEqual(proposta.data_hora_inicio, self.inicio)
        self.assertFalse(self.vaga.livre)

    def test_janela_desligada_recusa(self):
        self.chamada.aberta = False
        self.chamada.save(update_fields=["aberta"])

        with self.assertRaises(PropostaBloqueada):
            self._propor()

    def test_janela_futura_recusa(self):
        agora = timezone.now()
        self.chamada.inicio = agora + timedelta(days=1)
        self.chamada.fim = agora + timedelta(days=2)
        self.chamada.save(update_fields=["inicio", "fim"])

        with self.assertRaises(PropostaBloqueada):
            self._propor()

    def test_janela_encerrada_recusa(self):
        agora = timezone.now()
        self.chamada.inicio = agora - timedelta(days=10)
        self.chamada.fim = agora - timedelta(days=1)
        self.chamada.save(update_fields=["inicio", "fim"])

        with self.assertRaises(PropostaBloqueada):
            self._propor()

    def test_vaga_cheia_recusa(self):
        self._propor()
        outra = U.objects.create_user(
            email="outra_prop@example.com", password=SENHA, cpf="39053344705"
        )

        with self.assertRaises(PropostaBloqueada):
            propostas.propor(
                outra, self.evento, vaga=self.vaga, titulo="Segunda",
                descricao="d", tipo=self.tipo,
            )

    def test_vaga_de_outro_evento_recusa(self):
        outro_evento = Evento.objects.create(
            title="Outro", description="d", local="l",
            data_inicio=self.evento.data_inicio, data_fim=self.evento.data_fim,
            organizador=self.org,
        )
        espaco = Espaco.objects.create(nome="Sala 9", capacidade=10)
        vaga = Vaga.objects.create(
            evento=outro_evento, espaco=espaco, inicio=self.inicio, fim=self.fim,
        )

        with self.assertRaises(PropostaBloqueada):
            self._propor(vaga=vaga)

    def test_conflito_de_espaco_recusa(self):
        Atividade.objects.create(
            evento=self.evento, titulo="Abertura", descricao="d", local="Auditório",
            data_hora_inicio=self.inicio, data_hora_fim=self.fim, n_vagas=50,
            publicada=True,
        )

        with self.assertRaises(PropostaBloqueada) as contexto:
            self._propor()
        self.assertIn("Auditório", str(contexto.exception))

    def test_conflito_de_palestrante_recusa(self):
        convidada = U.objects.create_user(
            email="palestrante_prop@example.com", password=SENHA,
            cpf="39053344705", is_palestrante=True,
        )
        Atividade.objects.create(
            evento=self.evento, titulo="Mesa-redonda", descricao="d", local="Sala 2",
            data_hora_inicio=self.inicio, data_hora_fim=self.fim, n_vagas=50,
            publicada=True,
        ).palestrantes.add(convidada)

        with self.assertRaises(PropostaBloqueada) as contexto:
            self._propor(palestrantes=[convidada])
        self.assertIn(convidada.get_full_name(), str(contexto.exception))

    def test_rascunho_interno_do_organizador_tambem_bloqueia(self):
        Atividade.objects.create(
            evento=self.evento, titulo="Rascunho", descricao="d", local="Auditório",
            data_hora_inicio=self.inicio, data_hora_fim=self.fim, n_vagas=10,
            publicada=False,
        )

        with self.assertRaises(PropostaBloqueada):
            self._propor()

    def test_proposta_rejeitada_nao_bloqueia_a_vaga(self):
        proposta = self._propor()
        propostas.rejeitar(proposta, self.org, "Fora do escopo.")

        outra = U.objects.create_user(
            email="outra_prop@example.com", password=SENHA, cpf="39053344705"
        )
        nova = propostas.propor(
            outra, self.evento, vaga=self.vaga, titulo="Segunda tentativa",
            descricao="d", tipo=self.tipo,
        )
        self.assertEqual(nova.situacao, Atividade.SITUACAO_PENDENTE)

    def test_capacidade_maior_permite_duas_atividades(self):
        vaga = self._vaga(self.fim, self.fim + timedelta(hours=2), capacidade=2)
        outra = U.objects.create_user(
            email="outra_prop@example.com", password=SENHA, cpf="39053344705"
        )

        propostas.propor(
            self.pessoa, self.evento, vaga=vaga, titulo="A", descricao="d",
            tipo=self.tipo,
        )
        propostas.propor(
            outra, self.evento, vaga=vaga, titulo="B", descricao="d",
            tipo=self.tipo,
        )

        self.assertEqual(vaga.ocupadas, 2)
        self.assertFalse(vaga.livre)


class CicloDeVidaTests(BasePropostasTests):
    def test_aprovar_publica_e_promove_o_proponente_a_palestrante(self):
        proposta = self._propor(palestrantes=[self.pessoa])
        self.assertFalse(U.objects.get(pk=self.pessoa.pk).is_palestrante)

        propostas.aprovar(proposta, self.org, publicar=True)

        proposta.refresh_from_db()
        self.assertEqual(proposta.situacao, Atividade.SITUACAO_APROVADA)
        self.assertTrue(proposta.publicada)
        self.assertEqual(proposta.decidida_por, self.org)
        self.assertTrue(U.objects.get(pk=self.pessoa.pk).is_palestrante)

    def test_aprovar_sem_publicar_mantem_rascunho(self):
        proposta = self._propor()

        propostas.aprovar(proposta, self.org, publicar=False)

        proposta.refresh_from_db()
        self.assertEqual(proposta.situacao, Atividade.SITUACAO_APROVADA)
        self.assertFalse(proposta.publicada)

    def test_nao_promove_palestrante_sem_ele_na_atividade(self):
        proposta = self._propor()

        propostas.aprovar(proposta, self.org)

        self.assertFalse(U.objects.get(pk=self.pessoa.pk).is_palestrante)

    def test_rejeitar_exige_motivo_e_libera_a_vaga(self):
        proposta = self._propor()

        with self.assertRaises(PropostaBloqueada):
            propostas.rejeitar(proposta, self.org, "   ")

        propostas.rejeitar(proposta, self.org, "Já temos atividade nesse horário.")

        proposta.refresh_from_db()
        self.assertEqual(proposta.situacao, Atividade.SITUACAO_REJEITADA)
        self.assertFalse(proposta.publicada)
        self.assertIn("horário", proposta.motivo_rejeicao)
        self.assertTrue(self.vaga.livre)

    def test_aprovar_proposta_rejeitada_recusa(self):
        proposta = self._propor()
        propostas.rejeitar(proposta, self.org, "Não.")

        with self.assertRaises(PropostaBloqueada):
            propostas.aprovar(proposta, self.org)

    def test_cancelar_apaga_e_libera_a_vaga(self):
        proposta = self._propor()

        propostas.cancelar(proposta)

        self.assertFalse(Atividade.objects.filter(pk=proposta.pk).exists())
        self.assertTrue(self.vaga.livre)

    def test_cancelar_proposta_ja_decidida_recusa(self):
        proposta = self._propor()
        propostas.aprovar(proposta, self.org)

        with self.assertRaises(PropostaBloqueada):
            propostas.cancelar(proposta)

    def test_editar_troca_de_vaga_e_revalida(self):
        proposta = self._propor()
        outra_vaga = self._vaga(self.fim, self.fim + timedelta(hours=2))

        propostas.atualizar(
            proposta, vaga=outra_vaga, titulo="Novo título",
            descricao="nova descrição", tipo=self.tipo,
        )

        proposta.refresh_from_db()
        self.assertEqual(proposta.titulo, "Novo título")
        self.assertEqual(proposta.vaga_id, outra_vaga.pk)
        self.assertEqual(proposta.data_hora_inicio, outra_vaga.inicio)
        self.assertEqual(proposta.local, "Auditório")
        self.assertTrue(self.vaga.livre)

    def test_editar_com_chamada_fechada_recusa(self):
        proposta = self._propor()
        self.chamada.aberta = False
        self.chamada.save(update_fields=["aberta"])

        with self.assertRaises(PropostaBloqueada):
            propostas.atualizar(
                proposta, vaga=self.vaga, titulo="X", descricao="d", tipo=self.tipo,
            )


class VisibilidadeTests(BasePropostasTests):
    def test_proposta_nao_aparece_na_programacao(self):
        self._propor(titulo="Proposta invisível")

        html = self.client.get(
            reverse("eventos:programacao", args=[self.evento.id])
        ).content.decode()

        self.assertNotIn("Proposta invisível", html)

    def test_api_publica_esconde_a_proposta(self):
        proposta = self._propor(titulo="Proposta invisível")
        anonimo = APIClient()

        resposta = anonimo.get(f"/api/v1/atividades/{proposta.id}/")

        self.assertEqual(resposta.status_code, 404)

    def test_api_do_organizador_mostra_a_proposta(self):
        proposta = self._propor(titulo="Proposta invisível")
        cliente = APIClient()
        cliente.force_authenticate(user=self.org)

        resposta = cliente.get(f"/api/v1/atividades/{proposta.id}/")

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["titulo"], "Proposta invisível")

    def test_aprovada_e_publicada_aparece_na_programacao(self):
        proposta = self._propor(titulo="Atividade aprovada")
        propostas.aprovar(proposta, self.org, publicar=True)

        html = self.client.get(
            reverse("eventos:programacao", args=[self.evento.id])
        ).content.decode()

        self.assertIn("Atividade aprovada", html)


class BannerChamadaTests(BasePropostasTests):
    def test_home_mostra_a_chamada_aberta(self):
        self.chamada.titulo = "Chamada de propostas SNCT"
        self.chamada.save(update_fields=["titulo"])

        html = self.client.get(reverse("eventos:eventos")).content.decode()
        self.assertIn("Chamada de propostas SNCT", html)
        self.assertIn("Entrar e propor", html)   # anônimo: passa pelo login

        self.client.force_login(self.pessoa)
        html = self.client.get(reverse("eventos:eventos")).content.decode()
        self.assertIn("Propor atividade", html)

    def test_home_esconde_a_chamada_desligada(self):
        self.chamada.titulo = "Chamada de propostas SNCT"
        self.chamada.aberta = False
        self.chamada.save(update_fields=["titulo", "aberta"])

        html = self.client.get(reverse("eventos:eventos")).content.decode()

        self.assertNotIn("Chamada de propostas SNCT", html)


class TelasDoProponenteTests(BasePropostasTests):
    def test_anonimo_vai_para_o_login(self):
        resposta = self.client.get(
            reverse("participante:propor_atividade", args=[self.evento.id])
        )

        self.assertEqual(resposta.status_code, 302)
        self.assertIn("/accounts/login/", resposta["Location"])

    def test_formulario_mostra_a_vaga_livre(self):
        self.client.force_login(self.pessoa)

        resposta = self.client.get(
            reverse("participante:propor_atividade", args=[self.evento.id])
        )
        html = resposta.content.decode()

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Auditório", html)

    def test_propoe_pela_view(self):
        self.client.force_login(self.pessoa)

        resposta = self.client.post(
            reverse("participante:propor_atividade", args=[self.evento.id]),
            {
                "vaga": self.vaga.pk,
                "titulo": "Oficina de Robótica",
                "descricao": "d",
                "tipo": self.tipo.pk,
                "eu_sou_palestrante": "on",
            },
        )

        self.assertRedirects(resposta, reverse("participante:minhas_propostas"))
        proposta = Atividade.objects.get(titulo="Oficina de Robótica")
        self.assertEqual(proposta.proponente, self.pessoa)
        self.assertEqual(proposta.situacao, Atividade.SITUACAO_PENDENTE)
        self.assertIn(self.pessoa, proposta.palestrantes.all())
        self.assertEqual(proposta.n_vagas, 40)  # capacidade do espaço

    def test_com_chamada_fechada_a_view_nao_cria(self):
        self.chamada.aberta = False
        self.chamada.save(update_fields=["aberta"])
        self.client.force_login(self.pessoa)

        resposta = self.client.post(
            reverse("participante:propor_atividade", args=[self.evento.id]),
            {"vaga": self.vaga.pk, "titulo": "X", "descricao": "d", "tipo": self.tipo.pk},
        )

        self.assertRedirects(resposta, reverse("participante:minhas_propostas"))
        self.assertFalse(Atividade.objects.filter(titulo="X").exists())

    def test_minhas_propostas_lista_a_pendente(self):
        self._propor(titulo="Minha oficina")
        self.client.force_login(self.pessoa)

        html = self.client.get(reverse("participante:minhas_propostas")).content.decode()

        self.assertIn("Minha oficina", html)
        self.assertIn("aguardando aprovação", html)

    def test_cancelar_pela_view(self):
        proposta = self._propor()
        self.client.force_login(self.pessoa)

        resposta = self.client.post(
            reverse("participante:cancelar_proposta", args=[proposta.id])
        )

        self.assertRedirects(resposta, reverse("participante:minhas_propostas"))
        self.assertFalse(Atividade.objects.filter(pk=proposta.pk).exists())

    def test_nao_cancela_proposta_de_outra_pessoa(self):
        proposta = self._propor()
        outra = U.objects.create_user(
            email="outra_prop@example.com", password=SENHA, cpf="39053344705"
        )
        self.client.force_login(outra)

        resposta = self.client.post(
            reverse("participante:cancelar_proposta", args=[proposta.id])
        )

        self.assertEqual(resposta.status_code, 404)
        self.assertTrue(Atividade.objects.filter(pk=proposta.pk).exists())


class TelasDoOrganizadorTests(BasePropostasTests):
    def test_quem_nao_gerencia_recebe_403(self):
        outro = U.objects.create_user(
            email="ninguem@example.com", password=SENHA, cpf="39053344705"
        )
        self.client.force_login(outro)

        resposta = self.client.get(
            reverse("organizador:chamada_proposicoes", args=[self.evento.id])
        )

        self.assertEqual(resposta.status_code, 403)

    def test_salva_chamada_espaco_e_vaga(self):
        self.client.force_login(self.org)

        resposta = self.client.post(
            reverse("organizador:salvar_chamada", args=[self.evento.id]),
            {
                "chamada-titulo": "Chamada SNCT",
                "chamada-descricao": "Envie sua proposta",
                "chamada-inicio": "2026-01-01T08:00",
                "chamada-fim": "2026-12-31T18:00",
                "chamada-aberta": "on",
            },
        )
        self.assertRedirects(
            resposta,
            reverse("organizador:chamada_proposicoes", args=[self.evento.id]),
        )
        self.chamada.refresh_from_db()
        self.assertEqual(self.chamada.titulo, "Chamada SNCT")
        self.assertTrue(self.chamada.aberta)

        self.client.post(
            reverse("organizador:adicionar_espaco", args=[self.evento.id]),
            {"espaco-nome": "Laboratório 3", "espaco-capacidade": 25},
        )
        espaco = Espaco.objects.get(nome="Laboratório 3")

        self.client.post(
            reverse("organizador:adicionar_vaga", args=[self.evento.id]),
            {
                "vaga-espaco": espaco.pk,
                "vaga-inicio": f"{self.evento.data_inicio.isoformat()}T14:00",
                "vaga-fim": f"{self.evento.data_inicio.isoformat()}T16:00",
                "vaga-capacidade": 1,
            },
        )

        self.assertTrue(Vaga.objects.filter(espaco=espaco).exists())

    def test_nao_exclui_vaga_com_proposta(self):
        proposta = self._propor()
        self.client.force_login(self.org)

        self.client.post(reverse("organizador:excluir_vaga", args=[self.vaga.id]))

        self.assertTrue(Vaga.objects.filter(pk=self.vaga.pk).exists())
        self.assertTrue(Atividade.objects.filter(pk=proposta.pk).exists())

    def test_aprova_pela_view(self):
        proposta = self._propor()
        self.client.force_login(self.org)

        resposta = self.client.post(
            reverse("organizador:aprovar_proposta", args=[proposta.id]),
            {"publicar": "1", "tipo": self.tipo.pk},
        )

        self.assertRedirects(
            resposta,
            reverse("organizador:propostas_pendentes", args=[self.evento.id]),
        )
        proposta.refresh_from_db()
        self.assertTrue(proposta.publicada)
        self.assertEqual(proposta.situacao, Atividade.SITUACAO_APROVADA)

    def test_aprova_sem_publicar_pela_view(self):
        proposta = self._propor()
        self.client.force_login(self.org)

        self.client.post(
            reverse("organizador:aprovar_proposta", args=[proposta.id]),
            {"publicar": "0", "tipo": self.tipo.pk},
        )

        proposta.refresh_from_db()
        self.assertEqual(proposta.situacao, Atividade.SITUACAO_APROVADA)
        self.assertFalse(proposta.publicada)

    def test_rejeita_pela_view_com_motivo(self):
        proposta = self._propor()
        self.client.force_login(self.org)

        self.client.post(
            reverse("organizador:rejeitar_proposta", args=[proposta.id]),
            {"motivo": "Horário já ocupado pela abertura."},
        )

        proposta.refresh_from_db()
        self.assertEqual(proposta.situacao, Atividade.SITUACAO_REJEITADA)
        self.assertTrue(self.vaga.livre)

    def test_painel_mostra_o_numero_de_pendentes(self):
        self._propor()
        self.client.force_login(self.org)

        resposta = self.client.get(reverse("organizador:dashboard"))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context["eventos"][0].n_pendentes, 1)


class SugestaoDeTipoTests(TestCase):
    """Rede de segurança sem IA da sugestão de tipo."""

    def test_acha_tipo_existente_pelo_texto(self):
        nome, existente = sugerir_tipo_por_palavras(
            "Oficina de robótica", "prática maker no laboratório",
            ["Oficina", "Palestra"],
        )
        self.assertEqual(nome, "Oficina")
        self.assertTrue(existente)

    def test_propoe_nome_novo_por_palavra_chave(self):
        nome, existente = sugerir_tipo_por_palavras(
            "Hackathon de dados", "", ["Palestra"],
        )
        self.assertEqual(nome, "Competição")
        self.assertFalse(existente)

    def test_sem_evidencia_devolve_vazio(self):
        nome, existente = sugerir_tipo_por_palavras("Encontro", "", ["Palestra"])
        self.assertEqual(nome, "Reunião")
        self.assertFalse(existente)

    def test_sem_texto_nem_palavra_chave(self):
        nome, existente = sugerir_tipo_por_palavras("Zzz", "", ["Palestra"])
        self.assertEqual(nome, "")
        self.assertFalse(existente)


class CatalogoDeEspacosTests(BasePropostasTests):
    """O espaço é do catálogo da escola: o mesmo serve a vários eventos."""

    def _outro_evento(self):
        evento = Evento.objects.create(
            title="Segundo evento", description="d", local="Campus",
            data_inicio=self.evento.data_inicio, data_fim=self.evento.data_fim,
            organizador=self.org,
        )
        agora = timezone.now()
        ChamadaProposicoes.objects.create(
            evento=evento, inicio=agora - timedelta(days=1),
            fim=agora + timedelta(days=5), aberta=True,
        )
        return evento

    def test_mesmo_espaco_atende_varios_eventos(self):
        outro = self._outro_evento()
        # Janela diferente de propósito: a mesma sala não pode ter duas vagas
        # idênticas (constraint), mas pode atender eventos em horários distintos.
        vaga = Vaga.objects.create(
            evento=outro, espaco=self.espaco,
            inicio=self.fim, fim=self.fim + timedelta(hours=2),
        )

        proposta = propostas.propor(
            self.pessoa, outro, vaga=vaga, titulo="No segundo evento",
            descricao="d", tipo=self.tipo,
        )

        self.assertEqual(proposta.local, "Auditório")
        self.assertEqual(self.espaco.vagas.count(), 2)

    def test_form_avisa_espaco_duplicado_sem_acento(self):
        from eventos.forms import EspacoForm

        form = EspacoForm(data={"nome": "Auditorio", "capacidade": 10})

        self.assertFalse(form.is_valid())
        self.assertIn("já está no catálogo", str(form.errors["nome"][0]))

    def test_nomes_conhecidos_junta_catalogo_e_agenda(self):
        Atividade.objects.create(
            evento=self.evento, titulo="Abertura", descricao="d",
            local="Laboratório de Informática 1, Ginásio", n_vagas=10,
            data_hora_inicio=self.inicio, data_hora_fim=self.fim,
        )

        nomes = propostas.nomes_conhecidos()

        self.assertIn("Auditório", nomes)                  # do catálogo
        self.assertIn("Laboratório de Informática", nomes)  # apelido da agenda
        self.assertIn("Ginásio", nomes)                     # do local livre

    def test_organizador_exclui_espaco_sem_vaga(self):
        livre = Espaco.objects.create(nome="Sala 42", capacidade=10)
        self.client.force_login(self.org)

        self.client.post(
            reverse("organizador:excluir_espaco", args=[self.evento.id, livre.id])
        )

        self.assertFalse(Espaco.objects.filter(pk=livre.pk).exists())

    def test_organizador_nao_exclui_espaco_usado_por_outro_evento(self):
        outro = self._outro_evento()
        Vaga.objects.create(
            evento=outro, espaco=self.espaco,
            inicio=self.fim, fim=self.fim + timedelta(hours=2),
        )
        self.client.force_login(self.org)

        self.client.post(
            reverse("organizador:excluir_espaco", args=[self.evento.id, self.espaco.id])
        )

        self.assertTrue(Espaco.objects.filter(pk=self.espaco.pk).exists())

    def test_relaciona_varios_palestrantes_com_o_proponente(self):
        convidada = U.objects.create_user(
            email="pal1@example.com", password=SENHA, cpf="39053344705",
            is_palestrante=True, first_name="Ana", last_name="Souza",
        )
        outro = U.objects.create_user(
            email="pal2@example.com", password=SENHA, cpf="16899535009",
            is_palestrante=True, first_name="Bruno", last_name="Lima",
        )
        self.client.force_login(self.pessoa)

        self.client.post(
            reverse("participante:propor_atividade", args=[self.evento.id]),
            {
                "vaga": self.vaga.pk,
                "titulo": "Mesa-redonda",
                "descricao": "d",
                "tipo": self.tipo.pk,
                "palestrantes": [convidada.pk, outro.pk],
                "eu_sou_palestrante": "on",
            },
        )

        proposta = Atividade.objects.get(titulo="Mesa-redonda")
        self.assertEqual(proposta.palestrantes.count(), 3)
        self.assertIn(self.pessoa, proposta.palestrantes.all())


class LimiteDePropostasTests(BasePropostasTests):
    """Limite de propostas ativas por pessoa em cada evento (0 = sem limite)."""

    def _outra_vaga(self):
        return self._vaga(self.fim, self.fim + timedelta(hours=2))

    @override_settings(MAX_PROPOSTAS_POR_PROPONENTE=0)
    def test_sem_limite_por_padrao(self):
        self._propor()

        proposta = self._propor(vaga=self._outra_vaga(), titulo="Segunda")

        self.assertEqual(proposta.situacao, Atividade.SITUACAO_PENDENTE)

    @override_settings(MAX_PROPOSTAS_POR_PROPONENTE=1)
    def test_limite_bloqueia_a_segunda(self):
        self._propor()

        with self.assertRaises(PropostaBloqueada) as contexto:
            self._propor(vaga=self._outra_vaga(), titulo="Segunda")

        self.assertIn("limite de 1", str(contexto.exception))

    @override_settings(MAX_PROPOSTAS_POR_PROPONENTE=1)
    def test_rejeitada_libera_o_limite(self):
        proposta = self._propor()
        propostas.rejeitar(proposta, self.org, "Fora do escopo.")

        nova = self._propor(vaga=self._outra_vaga(), titulo="Segunda")

        self.assertEqual(nova.situacao, Atividade.SITUACAO_PENDENTE)

    @override_settings(MAX_PROPOSTAS_POR_PROPONENTE=2)
    def test_restantes_para_propor(self):
        self.assertEqual(
            propostas.restantes_para_propor(self.pessoa, self.evento), 2
        )

        self._propor()

        self.assertEqual(
            propostas.restantes_para_propor(self.pessoa, self.evento), 1
        )

    @override_settings(MAX_PROPOSTAS_POR_PROPONENTE=1)
    def test_formulario_avisa_o_limite(self):
        self.client.force_login(self.pessoa)

        html = self.client.get(
            reverse("participante:propor_atividade", args=[self.evento.id])
        ).content.decode()

        self.assertIn("ainda pode enviar 1 proposta", html)


class EdicaoDeEspacoTests(BasePropostasTests):
    """O catálogo de espaços pode ser editado (nome e capacidade) pelo modal."""

    def _url_editar(self):
        return reverse("organizador:editar_espaco", args=[self.evento.id, self.espaco.id])

    def test_organizador_edita_nome_e_capacidade(self):
        self.client.force_login(self.org)

        resposta = self.client.post(
            self._url_editar(),
            {"espaco_modal-nome": "Auditório Nobre", "espaco_modal-capacidade": 200},
        )

        self.assertRedirects(
            resposta,
            reverse("organizador:chamada_proposicoes", args=[self.evento.id]),
        )
        self.espaco.refresh_from_db()
        self.assertEqual(self.espaco.nome, "Auditório Nobre")
        self.assertEqual(self.espaco.capacidade, 200)

    def test_editar_para_nome_existente_e_recusado(self):
        Espaco.objects.create(nome="Quadra", capacidade=50)
        self.client.force_login(self.org)

        self.client.post(
            self._url_editar(),
            {"espaco_modal-nome": "quadra", "espaco_modal-capacidade": 10},
        )

        self.espaco.refresh_from_db()
        self.assertEqual(self.espaco.nome, "Auditório")
        self.assertEqual(self.espaco.capacidade, 40)

    def test_cartao_traz_os_dados_do_modal_de_edicao(self):
        self.client.force_login(self.org)

        html = self.client.get(
            reverse("organizador:chamada_proposicoes", args=[self.evento.id])
        ).content.decode()

        self.assertIn('id="modalEspaco"', html)
        self.assertIn(f'data-acao="{self._url_editar()}"', html)
        self.assertIn('data-nome="Auditório"', html)
        self.assertIn('data-capacidade="40"', html)
        self.assertIn('id="id_espaco_modal-nome"', html)
        # O formulário de edição não pode disputar id com o de "adicionar".
        self.assertIn('id="id_espaco-nome"', html)

    def test_formulario_de_espaco_abre_por_parametro(self):
        self.client.force_login(self.org)

        html = self.client.get(
            reverse("organizador:chamada_proposicoes", args=[self.evento.id])
            + "?abrir=espaco"
        ).content.decode()

        self.assertIn('id="formEspaco"', html)
        self.assertIn("collapse show", html)

    def test_erro_ao_adicionar_reabre_o_formulario(self):
        Espaco.objects.create(nome="Quadra", capacidade=50)
        self.client.force_login(self.org)

        resposta = self.client.post(
            reverse("organizador:adicionar_espaco", args=[self.evento.id]),
            {"espaco-nome": "quadra", "espaco-capacidade": 10},
        )

        self.assertIn("?abrir=espaco#espacos", resposta["Location"])
        self.assertEqual(Espaco.objects.count(), 2)

    def test_quem_nao_gerencia_nao_edita(self):
        outro = U.objects.create_user(
            email="ninguem2@example.com", password=SENHA, cpf="39053344705"
        )
        self.client.force_login(outro)

        resposta = self.client.post(
            self._url_editar(),
            {"espaco_modal-nome": "Hackeado", "espaco_modal-capacidade": 1},
        )

        self.assertEqual(resposta.status_code, 403)
        self.espaco.refresh_from_db()
        self.assertEqual(self.espaco.nome, "Auditório")


class GradeEmLoteTests(BasePropostasTests):
    """Gerador de grade: dias × blocos × espaços, sem duplicar."""

    def _url(self):
        return reverse("organizador:gerar_grade_lote", args=[self.evento.id])

    def _post(self, **dados):
        base = {
            "grade-dias": [self.evento.data_inicio.isoformat()],
            "grade-blocos": "08:00-10:00",
            "grade-espacos": [self.espaco.pk],
            "grade-capacidade": 1,
        }
        base.update(dados)
        return self.client.post(self._url(), base)

    def _total(self):
        return Vaga.objects.filter(evento=self.evento).count()

    def test_gera_dias_vezes_blocos_vezes_espacos(self):
        quadro = Espaco.objects.create(nome="Quadra", capacidade=10)
        self.client.force_login(self.org)

        resposta = self._post(**{
            "grade-dias": [self.evento.data_inicio.isoformat()],
            "grade-blocos": "08:00-10:00\n10:00-12:00",
            "grade-espacos": [self.espaco.pk, quadro.pk],
        })

        self.assertRedirects(
            resposta,
            reverse("organizador:chamada_proposicoes", args=[self.evento.id]),
        )
        # 1 dia × 2 blocos × 2 espaços = 4 novas + a vaga do setUp
        self.assertEqual(self._total(), 5)
        self.assertTrue(
            Vaga.objects.filter(
                evento=self.evento, espaco=quadro, inicio__hour=8
            ).exists()
        )

    def test_aplica_a_capacidade_informada(self):
        self.client.force_login(self.org)

        self._post(**{"grade-capacidade": 3})

        vaga = Vaga.objects.get(evento=self.evento, espaco=self.espaco, inicio__hour=8)
        self.assertEqual(vaga.capacidade, 3)

    def test_rodar_de_novo_nao_duplica(self):
        self.client.force_login(self.org)
        self._post()

        resposta = self._post()  # segunda vez: só encontra o que já existe

        self.assertRedirects(
            resposta,
            reverse("organizador:chamada_proposicoes", args=[self.evento.id]),
        )
        self.assertEqual(self._total(), 2)  # a do setUp + 1 gerada

    def test_dia_fora_do_evento_recusa(self):
        fora = (self.evento.data_fim + timedelta(days=1)).isoformat()
        self.client.force_login(self.org)

        resposta = self._post(**{"grade-dias": [fora]})

        self.assertIn("?abrir=grade#vagas", resposta["Location"])
        self.assertEqual(self._total(), 1)  # só a do setUp

    def test_bloco_invalido_recusa(self):
        self.client.force_login(self.org)

        for bloco in ("abc", "25:00-26:00", "10:00-09:00"):
            with self.subTest(bloco=bloco):
                resposta = self._post(**{"grade-blocos": bloco})
                self.assertIn("?abrir=grade#vagas", resposta["Location"])
                self.assertEqual(self._total(), 1)

    def test_sem_dia_e_sem_espaco_recusa(self):
        self.client.force_login(self.org)

        self.assertIn("?abrir=grade", self._post(**{"grade-dias": []})["Location"])
        self.assertIn("?abrir=grade", self._post(**{"grade-espacos": []})["Location"])
        self.assertEqual(self._total(), 1)

    def test_vaga_ja_existente_de_outro_evento_e_pulada(self):
        outro = Evento.objects.create(
            title="Outro evento", description="d", local="Campus",
            data_inicio=self.evento.data_inicio, data_fim=self.evento.data_fim,
            organizador=self.org,
        )
        inicio = timezone.make_aware(
            datetime.combine(self.evento.data_inicio, time(8, 0))
        )
        fim = timezone.make_aware(
            datetime.combine(self.evento.data_inicio, time(10, 0))
        )
        Vaga.objects.create(evento=outro, espaco=self.espaco, inicio=inicio, fim=fim)
        self.client.force_login(self.org)

        self._post()  # mesma janela, outro evento

        self.assertEqual(self._total(), 1)  # nada criado para este evento

    def test_quem_nao_gerencia_recebe_403(self):
        outro = U.objects.create_user(
            email="ninguem3@example.com", password=SENHA, cpf="39053344705"
        )
        self.client.force_login(outro)

        resposta = self._post()

        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(self._total(), 1)


class EdicaoDeVagaTests(BasePropostasTests):
    """A vaga da grade pode ser editada (modal), com travas quando há proposta."""

    def _url(self, vaga=None):
        return reverse(
            "organizador:editar_vaga",
            args=[self.evento.id, (vaga or self.vaga).id],
        )

    def _dados(self, **extra):
        inicio = extra.pop("inicio", self.vaga.inicio)
        fim = extra.pop("fim", self.vaga.fim)
        dados = {
            "vaga_modal-espaco": self.vaga.espaco_id,
            "vaga_modal-inicio": inicio.strftime("%Y-%m-%dT%H:%M"),
            "vaga_modal-fim": fim.strftime("%Y-%m-%dT%H:%M"),
            "vaga_modal-capacidade": self.vaga.capacidade,
        }
        dados.update(extra)
        return dados

    def test_organizador_edita_espaco_janela_e_capacidade(self):
        outro = Espaco.objects.create(nome="Quadra", capacidade=50)
        novo_inicio = self.inicio + timedelta(days=1)
        novo_fim = self.fim + timedelta(days=1)
        self.client.force_login(self.org)

        resposta = self.client.post(self._url(), self._dados(
            **{
                "vaga_modal-espaco": outro.pk,
                "vaga_modal-inicio": novo_inicio.strftime("%Y-%m-%dT%H:%M"),
                "vaga_modal-fim": novo_fim.strftime("%Y-%m-%dT%H:%M"),
                "vaga_modal-capacidade": 2,
            }
        ))

        self.assertRedirects(
            resposta,
            reverse("organizador:chamada_proposicoes", args=[self.evento.id]),
        )
        self.vaga.refresh_from_db()
        self.assertEqual(self.vaga.espaco, outro)
        self.assertEqual(self.vaga.inicio, novo_inicio)
        self.assertEqual(self.vaga.capacidade, 2)

    def test_recusa_dia_fora_do_evento(self):
        fora = datetime.combine(
            self.evento.data_fim + timedelta(days=1), time(14, 0)
        )
        self.client.force_login(self.org)

        resposta = self.client.post(self._url(), self._dados(
            **{"vaga_modal-inicio": fora.strftime("%Y-%m-%dT%H:%M"),
               "vaga_modal-fim": (fora + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")}
        ))

        self.assertIn("?abrir=vaga#vagas", resposta["Location"])
        self.vaga.refresh_from_db()
        self.assertEqual(self.vaga.inicio, self.inicio)

    def test_recusa_janela_duplicada_no_mesmo_espaco(self):
        ja_existe = self._vaga(self.fim, self.fim + timedelta(hours=2))
        self.client.force_login(self.org)

        resposta = self.client.post(self._url(), self._dados(
            **{"vaga_modal-inicio": ja_existe.inicio.strftime("%Y-%m-%dT%H:%M"),
               "vaga_modal-fim": ja_existe.fim.strftime("%Y-%m-%dT%H:%M")}
        ))

        self.assertIn("?abrir=vaga#vagas", resposta["Location"])
        self.vaga.refresh_from_db()
        self.assertEqual(self.vaga.inicio, self.inicio)

    def test_inicio_depois_do_fim_e_recusado(self):
        self.client.force_login(self.org)

        resposta = self.client.post(self._url(), self._dados(
            **{"vaga_modal-fim": self.inicio.strftime("%Y-%m-%dT%H:%M")}
        ))

        self.assertIn("?abrir=vaga#vagas", resposta["Location"])
        self.vaga.refresh_from_db()
        self.assertEqual(self.vaga.fim, self.fim)

    def test_bloqueia_espaco_e_horario_com_proposta_ativa(self):
        self._propor()  # proposta pendente nesta vaga
        outro = Espaco.objects.create(nome="Quadra", capacidade=50)
        self.client.force_login(self.org)

        resposta = self.client.post(self._url(), self._dados(
            **{"vaga_modal-espaco": outro.pk}
        ))

        self.assertIn("?abrir=vaga#vagas", resposta["Location"])
        self.vaga.refresh_from_db()
        self.assertEqual(self.vaga.espaco, self.espaco)

    def test_permite_mudar_capacidade_com_proposta_ativa(self):
        self._propor()
        self.client.force_login(self.org)

        resposta = self.client.post(self._url(), self._dados(
            **{"vaga_modal-capacidade": 3}
        ))

        self.assertRedirects(
            resposta,
            reverse("organizador:chamada_proposicoes", args=[self.evento.id]),
        )
        self.vaga.refresh_from_db()
        self.assertEqual(self.vaga.capacidade, 3)

    def test_recusa_capacidade_menor_que_as_propostas_ativas(self):
        self.vaga.capacidade = 2
        self.vaga.save(update_fields=["capacidade"])
        self._propor(vaga=self.vaga, titulo="A")
        self._propor(vaga=self.vaga, titulo="B")
        self.client.force_login(self.org)

        resposta = self.client.post(self._url(), self._dados(
            **{"vaga_modal-capacidade": 1}
        ))

        self.assertIn("?abrir=vaga#vagas", resposta["Location"])
        self.vaga.refresh_from_db()
        self.assertEqual(self.vaga.capacidade, 2)

    def test_cartao_traz_os_dados_do_modal(self):
        self.client.force_login(self.org)

        html = self.client.get(
            reverse("organizador:chamada_proposicoes", args=[self.evento.id])
        ).content.decode()

        self.assertIn('id="modalVaga"', html)
        self.assertIn(f'data-acao="{self._url()}"', html)
        self.assertIn(f'data-espaco="{self.espaco.pk}"', html)
        self.assertIn('data-capacidade="1"', html)
        self.assertIn('id="id_vaga_modal-espaco"', html)
        self.assertIn('id="id_vaga_modal-inicio"', html)

    def test_quem_nao_gerencia_nao_edita(self):
        outro = U.objects.create_user(
            email="ninguem4@example.com", password=SENHA, cpf="39053344705"
        )
        self.client.force_login(outro)

        resposta = self.client.post(self._url(), self._dados(
            **{"vaga_modal-capacidade": 9}
        ))

        self.assertEqual(resposta.status_code, 403)
        self.vaga.refresh_from_db()
        self.assertEqual(self.vaga.capacidade, 1)


class PainelDaChamadaTests(BasePropostasTests):
    """Resumo/indicadores da chamada (`propostas.resumo`) e a tela do painel."""

    def _tres_propostas(self):
        """Uma proposta em cada situação (pendente, aprovada, rejeitada)."""
        segunda = self._vaga(self.fim, self.fim + timedelta(hours=2))
        terceira = self._vaga(self.fim + timedelta(hours=2), self.fim + timedelta(hours=4))
        pendente = self._propor(titulo="Pendente")
        aprovada = self._propor(vaga=segunda, titulo="Aprovada")
        rejeitada = self._propor(vaga=terceira, titulo="Rejeitada")
        propostas.aprovar(aprovada, self.org)
        propostas.rejeitar(rejeitada, self.org, "Fora do escopo.")
        return pendente, aprovada, rejeitada

    def _kpi(self, resumo, rotulo):
        return next(k["valor"] for k in resumo["kpis"] if k["rotulo"] == rotulo)

    def test_resumo_conta_por_situacao_e_taxa(self):
        self._tres_propostas()

        resumo = propostas.resumo(self.evento)

        self.assertEqual(self._kpi(resumo, "Propostas"), 3)
        self.assertEqual(self._kpi(resumo, "Aguardando"), 1)
        self.assertEqual(self._kpi(resumo, "Aprovadas"), 1)
        self.assertEqual(self._kpi(resumo, "Rejeitadas"), 1)
        self.assertEqual(self._kpi(resumo, "Taxa de aprovação"), 50)

    def test_resumo_vagas_e_ocupacao(self):
        self._tres_propostas()

        resumo = propostas.resumo(self.evento)

        self.assertEqual(self._kpi(resumo, "Vagas na grade"), 3)
        # Rejeitada libera a vaga: das 3, duas seguem ocupadas (pendente e aprovada).
        self.assertEqual(self._kpi(resumo, "Vagas livres"), 1)
        self.assertEqual(self._kpi(resumo, "Ocupação da grade"), 67)
        self.assertEqual(len(resumo["vagas_livres"]), 1)
        bloco = resumo["por_espaco"][0]
        self.assertEqual(bloco["espaco"], self.espaco)
        self.assertEqual(bloco["total"], 3)
        self.assertEqual(bloco["livres"], 1)

    def test_resumo_aponta_a_proposta_de_cada_vaga(self):
        self._tres_propostas()

        resumo = propostas.resumo(self.evento)

        titulos = {
            item["proposta"].titulo
            for bloco in resumo["por_espaco"] for item in bloco["vagas"]
            if item["proposta"]
        }
        # Só o que ocupa a vaga aparece: a rejeitada devolveu a janela à grade.
        self.assertEqual(titulos, {"Pendente", "Aprovada"})

    def test_capacidade_dois_conta_como_uma_vaga(self):
        self.vaga.capacidade = 2
        self.vaga.save(update_fields=["capacidade"])

        self._propor(titulo="Primeira")
        resumo = propostas.resumo(self.evento)
        self.assertEqual(self._kpi(resumo, "Vagas livres"), 1)
        self.assertEqual(len(resumo["vagas_livres"]), 1)

        outra = U.objects.create_user(
            email="outra_painel@example.com", password=SENHA, cpf="39053344705"
        )
        propostas.propor(
            outra, self.evento, vaga=self.vaga, titulo="Segunda",
            descricao="d", tipo=self.tipo,
        )
        resumo = propostas.resumo(self.evento)
        self.assertEqual(self._kpi(resumo, "Vagas livres"), 0)
        self.assertEqual(self._kpi(resumo, "Ocupação da grade"), 100)

    def test_painel_responde_com_os_indicadores(self):
        self._tres_propostas()
        self.client.force_login(self.org)

        resposta = self.client.get(
            reverse("organizador:chamada_painel", args=[self.evento.id])
        )
        html = resposta.content.decode()

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.context["kpis"]), 8)
        self.assertIn("Painel da chamada", html)
        self.assertIn("Taxa de aprovação", html)
        self.assertIn("Ocupação por espaço", html)
        self.assertIn("Aprovada", html)

    def test_painel_403_para_quem_nao_gerencia(self):
        outro = U.objects.create_user(
            email="ninguem5@example.com", password=SENHA, cpf="39053344705"
        )
        self.client.force_login(outro)

        resposta = self.client.get(
            reverse("organizador:chamada_painel", args=[self.evento.id])
        )

        self.assertEqual(resposta.status_code, 403)

    def test_link_do_painel_no_cabecalho_da_chamada(self):
        self.client.force_login(self.org)

        html = self.client.get(
            reverse("organizador:chamada_proposicoes", args=[self.evento.id])
        ).content.decode()

        self.assertIn(
            reverse("organizador:chamada_painel", args=[self.evento.id]), html
        )
