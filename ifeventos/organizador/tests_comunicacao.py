"""Testes da comunicação por e-mail do organizador com o público do evento."""

import json
from datetime import date, datetime, time, timedelta
from unittest import mock
from unittest.mock import AsyncMock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from eventos import comunicados
from eventos.models import (
    Atividade,
    Evento,
    Inscricao,
    RegistroAuditoria,
    TipoAtividade,
)

U = get_user_model()
SENHA = "SenhaForte123!"


def _resposta_ia(conteudo):
    resposta = mock.MagicMock()
    resposta.choices = [mock.MagicMock()]
    resposta.choices[0].message.content = json.dumps(conteudo)
    resposta.usage = None
    return resposta


class BaseComunicacaoTests(TestCase):
    def setUp(self):
        self.org = self._pessoa(
            "org_com@example.com", "12345678909", "Ana", "Organizadora",
            is_organizador=True,
        )
        self.co = self._pessoa(
            "co_com@example.com", "39053344705", "Caio", "Coorganizador",
            is_organizador=True,
        )
        self.participante = self._pessoa(
            "part_com@example.com", "11144477735", "Paula", "Participante",
        )
        self.palestrante = self._pessoa(
            "pal_com@example.com", "15350946056", "Pedro", "Palestrante",
        )
        self.equipe = self._pessoa(
            "eq_com@example.com", "52998224725", "Eva", "Equipe",
        )
        self.comissao = self._pessoa(
            "com_com@example.com", "98765432100", "Carla", "Comissão",
        )
        self.outro_inscrito = self._pessoa(
            "outro_com@example.com", "12345678901", "Otávio", "Inscrito",
        )
        self.estranho = self._pessoa(
            "estranho_com@example.com", "98765432101", "Estevão", "Estranho",
        )

        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="SNCT 2026", description="Mostra de ciência e tecnologia.",
            local="Campus Ponte Nova",
            data_inicio=hoje + timedelta(days=10),
            data_fim=hoje + timedelta(days=11),
            organizador=self.org,
        )
        self.evento.organizadores.add(self.co)
        self.evento.equipe.add(self.equipe)
        self.evento.comissao.add(self.comissao)

        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        inicio = timezone.make_aware(
            datetime.combine(self.evento.data_inicio, time(14, 0))
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Oficina de Robótica",
            descricao="d", tipo=self.tipo, local="Lab 1",
            data_hora_inicio=inicio, data_hora_fim=inicio + timedelta(hours=2),
        )
        self.atividade.palestrantes.add(self.palestrante)
        self.outra_atividade = Atividade.objects.create(
            evento=self.evento, titulo="Palestra de IA",
            descricao="d", tipo=self.tipo, local="Auditório",
            data_hora_inicio=inicio + timedelta(days=1),
            data_hora_fim=inicio + timedelta(days=1, hours=1),
        )

        Inscricao.objects.create(
            participante=self.participante, atividade=self.atividade
        )
        # O palestrante também está inscrito: serve para provar a deduplicação.
        Inscricao.objects.create(
            participante=self.palestrante, atividade=self.atividade
        )
        Inscricao.objects.create(
            participante=self.outro_inscrito, atividade=self.outra_atividade
        )

    def _pessoa(self, email, cpf, nome, sobrenome, **extra):
        return U.objects.create_user(
            email=email, password=SENHA, cpf=cpf,
            first_name=nome, last_name=sobrenome, **extra,
        )

    def _url(self, nome="comunicacao_evento", **kwargs):
        return reverse("organizador:%s" % nome, args=[self.evento.id], **kwargs)

    def _post_envio(self, grupos=("palestrantes",), **extra):
        dados = {
            "assunto": "Lembrete do evento",
            "corpo": "Olá!\n\nNão esqueça da atividade.",
            "grupos": list(grupos),
            "nao_eu": "1",
        }
        dados.update(extra)
        return self.client.post(self._url(), dados)


class GruposEDestinatariosTests(BaseComunicacaoTests):
    def test_grupos_contam_pessoas(self):
        grupos = {g["chave"]: g["total"] for g in comunicados.grupos_com_contagem(self.evento)}
        self.assertEqual(grupos["organizadores"], 2)  # dono + co
        self.assertEqual(grupos["palestrantes"], 1)
        self.assertEqual(grupos["equipe"], 1)
        self.assertEqual(grupos["comissao"], 1)
        self.assertEqual(grupos["participantes"], 3)
        self.assertEqual(grupos["todos"], 7)  # ninguém repetido

    def test_inscritos_da_atividade_de_referencia(self):
        pessoas, sem_email = comunicados.destinatarios(
            self.evento,
            grupos=["inscritos_atividade"],
            atividade_id=self.atividade.id,
        )
        self.assertEqual(
            {p.id for p in pessoas},
            {self.participante.id, self.palestrante.id},
        )
        self.assertEqual(sem_email, [])

    def test_atividade_de_outro_evento_e_ignorada(self):
        outro_evento = Evento.objects.create(
            title="Outro evento", description="d", local="l",
            data_inicio=date(2026, 12, 1), data_fim=date(2026, 12, 2),
            organizador=self.org,
        )
        atividade_alheia = Atividade.objects.create(
            evento=outro_evento, titulo="Alheia", descricao="d",
            data_hora_inicio=timezone.now() + timedelta(days=1),
            data_hora_fim=timezone.now() + timedelta(days=1, hours=1),
        )
        pessoas, _ = comunicados.destinatarios(
            self.evento,
            grupos=["inscritos_atividade"],
            atividade_id=atividade_alheia.id,
        )
        self.assertEqual(pessoas, [])

    def test_deduplica_entre_grupos(self):
        # O palestrante também tem inscrição: entra uma vez só.
        pessoas, _ = comunicados.destinatarios(
            self.evento, grupos=["palestrantes", "participantes"]
        )
        self.assertEqual(len(pessoas), 3)
        self.assertEqual(len({p.email for p in pessoas}), 3)

    def test_exclui_o_proprio_organizador(self):
        pessoas, _ = comunicados.destinatarios(
            self.evento,
            grupos=["organizadores"],
            excluir=self.org,
        )
        self.assertEqual([p.id for p in pessoas], [self.co.id])

    def test_individual_vence_exclusao_de_mim(self):
        # A escolha explícita não é anulada pelo "não me incluir nos grupos".
        pessoas, _ = comunicados.destinatarios(
            self.evento,
            grupos=["organizadores"],
            pessoas_ids=[self.org.id],
            excluir=self.org,
        )
        self.assertEqual({p.id for p in pessoas}, {self.org.id, self.co.id})

    def test_resumo_explica_sobreposicao_e_exclusao(self):
        resumo = comunicados.resumo_selecao(
            self.evento,
            grupos=["comissao", "todos"],
            pessoas_ids=[self.palestrante.id],
            excluir=self.org,
        )
        self.assertEqual(resumo["grupos"], 7)
        self.assertEqual(resumo["repetidos"], 1)  # palestrante já está em "todos"
        self.assertEqual(resumo["excluido"], 1)   # você saiu dos grupos
        self.assertEqual(resumo["total"], 6)

    def test_resumo_individual_do_organizador_nao_conta_como_fora(self):
        resumo = comunicados.resumo_selecao(
            self.evento,
            grupos=["todos"],
            pessoas_ids=[self.org.id],
            excluir=self.org,
        )
        self.assertEqual(resumo["grupos"], 7)
        self.assertEqual(resumo["repetidos"], 1)
        self.assertEqual(resumo["excluido"], 0)  # voltou pela seleção individual
        self.assertEqual(resumo["total"], 7)

    def test_resumo_chip_sem_vinculo(self):
        resumo = comunicados.resumo_selecao(
            self.evento, pessoas_ids=[self.estranho.id]
        )
        self.assertEqual(resumo["nao_relacionados"], 1)
        self.assertEqual(resumo["total"], 0)

    def test_pessoa_sem_email_e_ignorada(self):
        U.objects.filter(pk=self.equipe.pk).update(email="")
        pessoas, sem_email = comunicados.destinatarios(
            self.evento, grupos=["equipe"]
        )
        self.assertEqual(pessoas, [])
        self.assertEqual([p.id for p in sem_email], [self.equipe.id])

    def test_busca_restrita_ao_evento(self):
        achados = comunicados.buscar_pessoas(self.evento, "Pedro")
        self.assertEqual([p["id"] for p in achados], [self.palestrante.id])
        self.assertEqual(comunicados.buscar_pessoas(self.evento, "Estevão"), [])


class TelaComunicacaoTests(BaseComunicacaoTests):
    def test_organizador_ve_a_tela(self):
        self.client.force_login(self.org)
        resposta = self.client.get(self._url())
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Destinatários")
        self.assertContains(resposta, "Enviar e-mails")
        self.assertContains(resposta, "Lembrete do evento")
        self.assertContains(resposta, 'id="btnGerarIa"')
        self.assertContains(resposta, 'data-carregando="Gerando…"')
        self.assertContains(resposta, "A IA está escrevendo o rascunho")

    def test_coorganizador_ve_a_tela(self):
        self.client.force_login(self.co)
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_botao_na_barra_do_evento(self):
        self.client.force_login(self.org)
        resposta = self.client.get(
            reverse("organizador:atividades_evento", args=[self.evento.id])
        )
        self.assertContains(resposta, "Enviar e-mails")
        self.assertContains(
            resposta,
            reverse("organizador:comunicacao_evento", args=[self.evento.id]),
        )

    def test_botao_no_card_do_evento(self):
        self.client.force_login(self.org)
        resposta = self.client.get(reverse("organizador:dashboard"))
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(
            resposta,
            reverse("organizador:comunicacao_evento", args=[self.evento.id]),
        )
        self.assertContains(resposta, 'title="Comunicação por e-mail"')

    def test_participante_recebe_403(self):
        self.client.force_login(self.participante)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_busca_endpoint(self):
        self.client.force_login(self.org)
        resposta = self.client.get(
            self._url("comunicacao_pessoas"), {"q": "Pedro"}
        )
        self.assertEqual(resposta.status_code, 200)
        pessoas = resposta.json()["pessoas"]
        self.assertEqual([p["id"] for p in pessoas], [self.palestrante.id])

    def test_contagem_endpoint(self):
        self.client.force_login(self.org)
        resposta = self.client.get(
            self._url("comunicacao_contar"),
            {"grupos": ["organizadores"], "nao_eu": "1"},
        )
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados["total"], 1)  # só o co
        self.assertEqual(dados["grupos"], 2)
        self.assertEqual(dados["excluido"], 1)

    def test_contagem_individual_inclui_o_organizador(self):
        self.client.force_login(self.org)
        resposta = self.client.get(
            self._url("comunicacao_contar"),
            {"pessoas": [self.org.id], "nao_eu": "1"},
        )
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados["total"], 1)
        self.assertEqual(dados["excluido"], 0)
        self.assertEqual(dados["repetidos"], 0)


class EnvioComunicadoTests(BaseComunicacaoTests):
    def test_envia_um_email_por_pessoa(self):
        self.client.force_login(self.org)
        resposta = self._post_envio()
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        mensagem = mail.outbox[0]
        self.assertEqual(mensagem.to, [self.palestrante.email])
        self.assertEqual(mensagem.subject, "Lembrete do evento")
        self.assertIn("Não esqueça", mensagem.body)
        self.assertEqual(mensagem.reply_to, [self.org.email])

    def test_envio_para_individuais(self):
        self.client.force_login(self.org)
        resposta = self._post_envio(
            grupos=(), pessoas=[self.equipe.id, self.comissao.id]
        )
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual(
            sorted(m.to[0] for m in mail.outbox),
            sorted([self.equipe.email, self.comissao.email]),
        )

    def test_envio_individual_para_mim_ignora_nao_eu(self):
        self.client.force_login(self.org)
        resposta = self._post_envio(grupos=(), pessoas=[self.org.id])
        self.assertEqual(resposta.status_code, 302)
        self.assertEqual([m.to[0] for m in mail.outbox], [self.org.email])

    def test_sem_destinatario_nao_envia(self):
        self.client.force_login(self.org)
        resposta = self._post_envio(grupos=())
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "pelo menos um destinatário")
        self.assertEqual(len(mail.outbox), 0)

    def test_sem_assunto_ou_corpo_nao_envia(self):
        self.client.force_login(self.org)
        resposta = self._post_envio(corpo="")
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Escreva a mensagem")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(COMUNICADOS_MAX_DESTINATARIOS=1)
    def test_limite_por_disparo(self):
        self.client.force_login(self.org)
        resposta = self._post_envio(grupos=["organizadores"], nao_eu="")
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "acima do limite")
        self.assertEqual(len(mail.outbox), 0)

    def test_envio_grava_auditoria(self):
        self.client.force_login(self.org)
        self._post_envio()
        registro = RegistroAuditoria.objects.get(
            acao=RegistroAuditoria.ACAO_ENVIAR_COMUNICADO
        )
        self.assertEqual(registro.evento_id, self.evento.id)
        self.assertEqual(registro.detalhes["total"], 1)
        self.assertEqual(registro.detalhes["assunto"], "Lembrete do evento")

    def test_mensagem_de_sucesso(self):
        self.client.force_login(self.org)
        resposta = self._post_envio()
        resposta = self.client.get(self._url())
        self.assertContains(resposta, "enfileirado")


class IaDoComunicadoTests(BaseComunicacaoTests):
    def _post_ia(self):
        return self.client.post(
            self._url("comunicacao_ia"),
            data=json.dumps({
                "modelo": "lembrete_evento",
                "atividade_id": self.atividade.id,
                "publico": "Palestrantes",
                "objetivo": "lembrar do horário",
            }),
            content_type="application/json",
        )

    def test_ia_gera_assunto_e_corpo(self):
        self.client.force_login(self.org)
        with mock.patch(
            "eventos.comunicacao.services.gerar_chat",
            new=AsyncMock(return_value=_resposta_ia({
                "assunto": "Lembrete da oficina",
                "corpo": "Olá! A oficina começa às 14h.",
            })),
        ):
            resposta = self._post_ia()
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados["assunto"], "Lembrete da oficina")
        self.assertEqual(dados["origem"], "ia")

    def test_ia_remove_markdown(self):
        self.client.force_login(self.org)
        with mock.patch(
            "eventos.comunicacao.services.gerar_chat",
            new=AsyncMock(return_value=_resposta_ia({
                "assunto": "Lembrete **SNCT 2026**",
                "corpo": "Olá!\n\n**5 a 9 de outubro** no **IFMG**.\n- Traga seu crachá",
            })),
        ):
            resposta = self._post_ia()
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertNotIn("**", dados["assunto"])
        self.assertNotIn("**", dados["corpo"])
        self.assertIn("5 a 9 de outubro", dados["corpo"])
        self.assertNotIn("- Traga", dados["corpo"])

    def test_ia_indisponivel_cai_no_modelo_padrao(self):
        self.client.force_login(self.org)
        with mock.patch(
            "eventos.comunicacao.services.gerar_chat",
            new=AsyncMock(side_effect=RuntimeError("sem chave")),
        ):
            resposta = self._post_ia()
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados["origem"], "heuristica")
        self.assertTrue(dados["assunto"])
        self.assertTrue(dados["corpo"])
        self.assertIn("modelo padrão", dados["aviso"])

    def test_ia_negada_para_participante(self):
        self.client.force_login(self.participante)
        self.assertEqual(self._post_ia().status_code, 403)
