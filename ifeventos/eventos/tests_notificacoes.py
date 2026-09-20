"""Testes dos avisos por e-mail e da busca de palestrante da chamada.

O envio de e-mail é *best-effort*: só acontece com `PROPOSTAS_NOTIFICAR_EMAIL`
ligado (padrão desligado), roda no commit da transação e nunca derruba a ação
principal. A busca de palestrante deixa escolher qualquer participante
cadastrado, sem mexer na flag global de palestrante.

O backend assíncrono é testado à parte: nos testes o Django força o `locmem`,
então a classe é exercitada direto (sem tocar em SMTP de verdade).
"""

from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.mail import EmailMessage
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from eventos import mail_backend, propostas
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


class _BaseChamadaTests(TestCase):
    def setUp(self):
        self.org = U.objects.create_user(
            email="org_aviso@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True, first_name="Organizadora",
        )
        self.pessoa = U.objects.create_user(
            email="pessoa_aviso@example.com", password=SENHA, cpf="11144477735",
            first_name="Proponente",
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento dos Avisos", description="d", local="Campus",
            data_inicio=hoje + timedelta(days=10), data_fim=hoje + timedelta(days=12),
            organizador=self.org,
        )
        agora = timezone.now()
        ChamadaProposicoes.objects.create(
            evento=self.evento, inicio=agora - timedelta(days=1),
            fim=agora + timedelta(days=5), aberta=True,
        )
        self.espaco = Espaco.objects.create(nome="Auditório", capacidade=40)
        dia = self.evento.data_inicio
        self.inicio = timezone.make_aware(datetime.combine(dia, time(14, 0)))
        self.fim = timezone.make_aware(datetime.combine(dia, time(16, 0)))
        self.vaga = Vaga.objects.create(
            evento=self.evento, espaco=self.espaco, inicio=self.inicio, fim=self.fim,
        )

    def _propor(self, **extra):
        dados = {
            "vaga": self.vaga, "titulo": "Minha proposta", "descricao": "d",
            "tipo": self.tipo,
        }
        dados.update(extra)
        return propostas.propor(self.pessoa, self.evento, **dados)

    def _criar_pessoa(self, nome="Maria", sobrenome="Souza", email="maria@example.com"):
        return U.objects.create_user(
            email=email, password=SENHA, cpf="39053344705",
            first_name=nome, last_name=sobrenome,
        )


class EmailsDaChamadaTests(_BaseChamadaTests):
    def test_desligado_por_padrao_nao_envia(self):
        with self.captureOnCommitCallbacks(execute=True), \
                override_settings(PROPOSTAS_NOTIFICAR_EMAIL=False):
            self._propor()

        self.assertEqual(len(mail.outbox), 0)

    @override_settings(PROPOSTAS_NOTIFICAR_EMAIL=True)
    def test_proposta_nova_avisa_o_organizador(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._propor()

        self.assertEqual(len(mail.outbox), 1)
        mensagem = mail.outbox[0]
        self.assertEqual(mensagem.to, [self.org.email])
        self.assertIn("Minha proposta", mensagem.subject)
        self.assertIn("Proponente", mensagem.body)
        self.assertIn(reverse("organizador:propostas_pendentes", args=[self.evento.id]),
                      mensagem.body)

    @override_settings(PROPOSTAS_NOTIFICAR_EMAIL=True)
    def test_aprovacao_avisa_o_proponente(self):
        proposta = self._propor()

        with self.captureOnCommitCallbacks(execute=True):
            propostas.aprovar(proposta, self.org)

        self.assertEqual(len(mail.outbox), 1)
        mensagem = mail.outbox[0]
        self.assertEqual(mensagem.to, [self.pessoa.email])
        self.assertIn("aprovada", mensagem.subject.lower())
        self.assertIn(reverse("participante:minhas_propostas"), mensagem.body)

    @override_settings(PROPOSTAS_NOTIFICAR_EMAIL=True)
    def test_rejeicao_avisa_com_o_motivo(self):
        proposta = self._propor()

        with self.captureOnCommitCallbacks(execute=True):
            propostas.rejeitar(proposta, self.org, "Fora do escopo do evento.")

        mensagem = mail.outbox[0]
        self.assertEqual(mensagem.to, [self.pessoa.email])
        self.assertIn("Fora do escopo do evento.", mensagem.body)

    @override_settings(PROPOSTAS_NOTIFICAR_EMAIL=True)
    def test_evento_sem_organizador_nao_quebra(self):
        self.evento.organizador = None
        self.evento.save(update_fields=["organizador"])

        with self.captureOnCommitCallbacks(execute=True):
            self._propor()

        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(Atividade.objects.count(), 1)

    @override_settings(PROPOSTAS_NOTIFICAR_EMAIL=True)
    def test_falha_no_envio_nao_derruba_a_proposta(self):
        with mock.patch("eventos.emails.send_mail", side_effect=OSError("smtp fora")):
            with self.captureOnCommitCallbacks(execute=True):
                proposta = self._propor()

        self.assertTrue(Atividade.objects.filter(pk=proposta.pk).exists())


class BuscaDePalestranteTests(_BaseChamadaTests):
    def _buscar(self, termo):
        self.client.force_login(self.pessoa)
        return self.client.get(
            reverse("participante:buscar_participante"), {"q": termo}
        )

    def test_exige_login(self):
        resposta = self.client.get(
            reverse("participante:buscar_participante"), {"q": "maria"}
        )

        self.assertEqual(resposta.status_code, 302)

    def test_termo_curto_devolve_vazio(self):
        self._criar_pessoa()

        self.assertEqual(self._buscar("ma").json()["resultados"], [])

    def test_acha_por_nome_e_por_email(self):
        maria = self._criar_pessoa()

        por_nome = self._buscar("souza").json()["resultados"]
        por_email = self._buscar("maria@").json()["resultados"]

        self.assertEqual([item["id"] for item in por_nome], [maria.pk])
        self.assertEqual([item["id"] for item in por_email], [maria.pk])
        self.assertFalse(por_nome[0]["palestrante"])

    def test_nao_devolve_quem_esta_buscando(self):
        self.assertEqual(self._buscar("pessoa_aviso").json()["resultados"], [])

    def test_proposta_aceita_palestrante_sem_flag(self):
        maria = self._criar_pessoa()
        self.client.force_login(self.pessoa)

        self.client.post(
            reverse("participante:propor_atividade", args=[self.evento.id]),
            {
                "vaga": self.vaga.pk,
                "titulo": "Mesa-redonda",
                "descricao": "d",
                "tipo": self.tipo.pk,
                "palestrantes_extra": [maria.pk],
                "consentimento_voluntario": "on",
            },
        )

        proposta = Atividade.objects.get(titulo="Mesa-redonda")
        self.assertIn(maria, proposta.palestrantes.all())
        maria.refresh_from_db()
        self.assertFalse(maria.is_palestrante, "o flag global não muda aqui")

    def test_id_invalido_e_ignorado(self):
        self.client.force_login(self.pessoa)

        self.client.post(
            reverse("participante:propor_atividade", args=[self.evento.id]),
            {
                "vaga": self.vaga.pk,
                "titulo": "Mesa-redonda",
                "descricao": "d",
                "tipo": self.tipo.pk,
                "palestrantes_extra": ["abc", "999999"],
                "consentimento_voluntario": "on",
            },
        )

        proposta = Atividade.objects.get(titulo="Mesa-redonda")
        self.assertEqual(proposta.palestrantes.count(), 0)

    def test_edicao_preserva_palestrante_sem_flag(self):
        maria = self._criar_pessoa()
        proposta = self._propor()
        proposta.palestrantes.add(maria)
        self.client.force_login(self.pessoa)
        url = reverse("participante:editar_proposta", args=[proposta.pk])

        html = self.client.get(url).content.decode()
        self.assertIn(f'data-extra="{maria.pk}"', html)

        self.client.post(url, {
            "vaga": self.vaga.pk,
            "titulo": "Minha proposta",
            "descricao": "d",
            "tipo": self.tipo.pk,
            "palestrantes_extra": [maria.pk],
            "consentimento_voluntario": "on",
        })

        self.assertIn(
            maria,
            Atividade.objects.get(pk=proposta.pk).palestrantes.all(),
        )


class AsyncEmailBackendTests(TestCase):
    """O backend assíncrono despacha e devolve na hora; o envio real é ``_enviar``."""

    def _mensagem(self, destino="alguem@example.com"):
        return EmailMessage("Assunto", "Corpo", None, [destino])

    def test_send_messages_delega_para_o_pool_sem_enviar_na_hora(self):
        backend = mail_backend.AsyncEmailBackend()

        with mock.patch("eventos.mail_backend._pool") as pool:
            enviadas = backend.send_messages(
                [self._mensagem("a@example.com"), self._mensagem("b@example.com")]
            )

        self.assertEqual(enviadas, 2)
        pool.submit.assert_called_once()
        _funcao, _kwargs, mensagens = pool.submit.call_args.args
        self.assertEqual(len(mensagens), 2)

    def test_send_messages_vazio_nao_despacha(self):
        backend = mail_backend.AsyncEmailBackend()

        with mock.patch("eventos.mail_backend._pool") as pool:
            self.assertEqual(backend.send_messages([]), 0)

        pool.submit.assert_not_called()

    def test_enviar_usa_backend_smtp_proprio_e_fecha(self):
        falso = mock.Mock()

        with mock.patch(
            "eventos.mail_backend.EmailBackend", return_value=falso
        ) as classe:
            mail_backend._enviar({"host": "smtp.gmail.com"}, [self._mensagem()])

        classe.assert_called_once_with(host="smtp.gmail.com")
        falso.send_messages.assert_called_once()
        falso.close.assert_called_once()

    def test_falha_no_envio_nao_levanta(self):
        with mock.patch(
            "eventos.mail_backend.EmailBackend", side_effect=OSError("smtp fora")
        ):
            mail_backend._enviar({}, [self._mensagem()])  # não pode levantar
