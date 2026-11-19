"""Página pública de validação de certificados.

O QR do certificado e o do crachá compartilham a rota curta `/c/<token>/`, mas
a apresentação e a regra de validade são diferentes: certificado é autenticado
pelo próprio registro em `Certificado`; crachá, pelo vínculo atual da pessoa.
"""

from datetime import date, datetime, timezone as tz
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from . import certificados
from .crachas import gerar_token
from .models import Atividade, Certificado, Evento, Inscricao

U = get_user_model()
SENHA = "SenhaForte123!"


class VerificacaoCertificadoTests(TestCase):
    def setUp(self):
        self.dono = U.objects.create_user(
            email="dono@verifica.test", password=SENHA, is_organizador=True
        )
        self.pessoa = U.objects.create_user(
            email="pessoa@verifica.test",
            password=SENHA,
            first_name="Luciano",
            last_name="Vilas Boas",
        )
        self.evento = Evento.objects.create(
            organizador=self.dono,
            title="Semana Nacional de Ciência e Tecnologia",
            description="d",
            local="Ponte Nova",
            data_inicio=date(2026, 10, 10),
            data_fim=date(2026, 10, 12),
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento,
            titulo="Oficina de Robótica",
            descricao="d",
            local="Laboratório 2",
            data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 10, 12, 0, tzinfo=tz.utc),
            n_vagas=10,
            emite_certificado=True,
            carga_horaria=2,
        )
        self.emissao = datetime(2026, 10, 17, 12, 0, tzinfo=tz.utc)

    def _certificado_atividade(self):
        return Certificado.objects.create(
            participante=self.pessoa,
            atividade=self.atividade,
            tipo=Certificado.TIPO_ATIVIDADE,
            carga_horaria=2,
            data_emissao=self.emissao,
        )

    def _token(self, **kwargs):
        return gerar_token(
            self.pessoa.id,
            evento_id=self.evento.id,
            tipo="certificado",
            **kwargs,
        )

    def _pagina(self, token):
        return self.client.get(reverse("verificar_cracha", args=[token]))

    def test_certificado_de_atividade_mostra_os_dados_do_registro(self):
        certificado = self._certificado_atividade()
        token = self._token(atividade_id=self.atividade.id)

        resposta = self._pagina(token)
        html = resposta.content.decode()

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Certificado válido", html)
        self.assertIn("Luciano Vilas Boas", html)
        self.assertIn("Participante", html)
        self.assertIn("Semana Nacional de Ciência e Tecnologia", html)
        self.assertIn("10 a 12/10/2026", html)
        self.assertIn("Laboratório 2", html)
        self.assertIn("Oficina de Robótica", html)
        self.assertIn("2h", html)
        self.assertIn("17/10/2026", html)
        self.assertIn(str(certificado.codigo).upper(), html)
        self.assertIn(reverse("eventos:programacao", args=[self.evento.id]), html)
        # A página de certificado não é a de crachá.
        self.assertNotIn("Crachá válido", html)
        self.assertNotIn("Presenças de", html)

    def test_certificado_de_funcao_mostra_a_funcao(self):
        certificado = Certificado.objects.create(
            participante=self.pessoa,
            evento=self.evento,
            tipo=Certificado.TIPO_FUNCAO,
            funcao="palestrante",
            data_emissao=self.emissao,
        )
        token = self._token(funcao="palestrante")

        html = self._pagina(token).content.decode()

        self.assertIn("Certificado válido", html)
        self.assertIn("Palestrante", html)
        self.assertIn(str(certificado.codigo).upper(), html)
        # Função não tem carga horária no registro.
        self.assertNotIn("Carga horária", html)

    def test_certificado_do_evento_nao_inventa_carga_horaria(self):
        Certificado.objects.create(
            participante=self.pessoa,
            evento=self.evento,
            tipo=Certificado.TIPO_EVENTO,
            data_emissao=self.emissao,
        )
        token = self._token()

        html = self._pagina(token).content.decode()

        self.assertIn("Certificado válido", html)
        self.assertIn("Participante", html)
        self.assertNotIn("Carga horária", html)
        self.assertNotIn("Oficina de Robótica", html)

    def test_pessoa_inscrita_sem_certificado_nao_e_aceita(self):
        # A inscrição (e o crachá) existem, mas não há registro de certificado.
        Inscricao.objects.create(participante=self.pessoa, atividade=self.atividade)
        token = self._token()

        resposta = self._pagina(token)
        html = resposta.content.decode()

        self.assertEqual(resposta.status_code, 404)
        self.assertIn("Certificado inválido", html)
        self.assertNotIn("Certificado válido", html)
        self.assertNotIn("Crachá válido", html)

    def test_certificado_revogado_nao_e_apresentado_como_valido(self):
        certificado = self._certificado_atividade()
        certificado.revogado_em = self.emissao
        certificado.motivo_revogacao = "Emitido em duplicidade"
        certificado.save(update_fields=["revogado_em", "motivo_revogacao"])
        token = self._token(atividade_id=self.atividade.id)

        resposta = self._pagina(token)
        html = resposta.content.decode()

        self.assertEqual(resposta.status_code, 410)
        self.assertIn("Certificado revogado", html)
        self.assertIn("não tem validade", html)
        self.assertIn("Luciano Vilas Boas", html)
        self.assertNotIn("Certificado válido", html)

    def test_token_adulterado_nao_quebra_e_nao_parece_certificado(self):
        resposta = self._pagina("isto-nao-e-um-token")

        self.assertEqual(resposta.status_code, 404)
        html = resposta.content.decode()
        self.assertIn("Não foi possível verificar este código", html)
        self.assertNotIn("Crachá válido", html)

    def test_certificado_de_pessoa_sem_papel_no_evento_vale_pelo_registro(self):
        # A fonte de verdade é o registro emitido — não o crachá/inscrição.
        Certificado.objects.create(
            participante=self.pessoa,
            evento=self.evento,
            tipo=Certificado.TIPO_FUNCAO,
            funcao="comissao",
            data_emissao=self.emissao,
        )
        token = self._token(funcao="comissao")

        resposta = self._pagina(token)

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Comissão organizadora", resposta.content.decode())

    def test_cracha_continua_com_a_pagina_de_cracha(self):
        Inscricao.objects.create(participante=self.pessoa, atividade=self.atividade)
        token = gerar_token(self.pessoa.id, self.evento.id, tipo="cracha")

        resposta = self._pagina(token)
        html = resposta.content.decode()

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Crachá válido", html)
        self.assertIn("Participante", html)
        self.assertNotIn("Certificado válido", html)

    def test_qr_gerado_pelo_certificado_abre_a_pagina_certa(self):
        self._certificado_atividade()
        contexto = certificados.contexto_certificado(
            self.pessoa, atividade=self.atividade
        )
        caminho = urlparse(contexto["qr_url"]).path

        resposta = self.client.get(caminho)

        self.assertEqual(resposta.status_code, 200)
        self.assertIn("Certificado válido", resposta.content.decode())

    def test_falha_tecnica_responde_503_sem_500(self):
        from unittest import mock

        with mock.patch(
            "eventos.views.verificar_token", side_effect=RuntimeError("banco fora")
        ):
            resposta = self._pagina("qualquer-token")

        self.assertEqual(resposta.status_code, 503)
        self.assertIn("Não foi possível consultar os dados agora", resposta.content.decode())

    def test_api_do_certificado_devolve_os_campos_do_registro(self):
        certificado = self._certificado_atividade()
        token = self._token(atividade_id=self.atividade.id)

        resposta = self.client.get(f"/api/v1/verificar/{token}/")
        dados = resposta.json()

        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(dados["valido"])
        self.assertEqual(dados["tipo"], "certificado")
        self.assertEqual(dados["situacao"], "valido")
        self.assertEqual(dados["nome"], "Luciano Vilas Boas")
        self.assertEqual(dados["tipo_participacao"], "Participante")
        self.assertEqual(dados["periodo"], "10 a 12/10/2026")
        self.assertEqual(dados["local"], "Laboratório 2")
        self.assertEqual(dados["carga_horaria"], 2)
        self.assertEqual(dados["codigo_autenticacao"], str(certificado.codigo).upper())
        self.assertEqual(dados["evento_id"], self.evento.id)
        self.assertEqual(dados["atividade_id"], self.atividade.id)

    def test_api_do_certificado_revogado_responde_410(self):
        certificado = self._certificado_atividade()
        certificado.revogado_em = self.emissao
        certificado.save(update_fields=["revogado_em"])
        token = self._token(atividade_id=self.atividade.id)

        resposta = self.client.get(f"/api/v1/verificar/{token}/")
        dados = resposta.json()

        self.assertEqual(resposta.status_code, 410)
        self.assertFalse(dados["valido"])
        self.assertEqual(dados["situacao"], "revogado")
        self.assertEqual(dados["codigo_autenticacao"], str(certificado.codigo).upper())
