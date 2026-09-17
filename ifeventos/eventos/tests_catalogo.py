"""Testes do catálogo de espaços: comando de sincronizar `local`, busca, admin.

O `local` da atividade é texto (não é FK para o espaço), então renomear um
espaço no catálogo não alcança o que já está gravado — é o que o comando
`sincronizar_locais` resolve.
"""

from datetime import datetime, time, timedelta
from io import StringIO

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from eventos.forms import VagaForm
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


class SincronizarLocaisTests(TestCase):
    """Comando que reescreve o `local` das atividades depois de renomear espaço."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_loc@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        self.tipo = TipoAtividade.objects.create(nome="Oficina")
        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento dos Locais", description="d", local="Campus",
            data_inicio=hoje + timedelta(days=10), data_fim=hoje + timedelta(days=12),
            organizador=self.org,
        )
        self.outro = Evento.objects.create(
            title="Outro evento", description="d", local="Campus",
            data_inicio=hoje + timedelta(days=10), data_fim=hoje + timedelta(days=12),
            organizador=self.org,
        )
        self.inicio = timezone.make_aware(
            datetime.combine(self.evento.data_inicio, time(8, 0))
        )
        self.fim = self.inicio + timedelta(hours=2)

    def _atividade(self, titulo, local, evento=None):
        return Atividade.objects.create(
            evento=evento or self.evento, titulo=titulo, descricao="d", local=local,
            tipo=self.tipo, data_hora_inicio=self.inicio, data_hora_fim=self.fim,
            n_vagas=10,
        )

    def _rodar(self, de, para, evento=None, aplicar=False):
        argumentos = ["--de", de, "--para", para]
        if evento is not None:
            argumentos += ["--evento", str(evento.id)]
        if aplicar:
            argumentos.append("--aplicar")
        saida = StringIO()
        call_command("sincronizar_locais", *argumentos, stdout=saida)
        return saida.getvalue()

    def test_troca_token_isolado(self):
        atividade = self._atividade("Abertura", "Auditório")

        self._rodar("Auditório", "Auditório Nobre", aplicar=True)

        atividade.refresh_from_db()
        self.assertEqual(atividade.local, "Auditório Nobre")

    def test_troca_token_dentro_de_lista(self):
        atividade = self._atividade("Mesa", "Sala de aula, Auditório")

        self._rodar("Auditório", "Auditório Nobre", aplicar=True)

        atividade.refresh_from_db()
        self.assertEqual(atividade.local, "Sala de aula, Auditório Nobre")

    def test_comparacao_ignora_acento_e_caixa(self):
        atividade = self._atividade("Abertura", "AUDITORIO")

        self._rodar("auditório", "Auditório Nobre", aplicar=True)

        atividade.refresh_from_db()
        self.assertEqual(atividade.local, "Auditório Nobre")

    def test_apelido_da_agenda_tambem_e_atualizado(self):
        # AGENDA_ALIASES_LOCAL mapeia "Laboratório de Informática 1" -> canônico.
        atividade = self._atividade("Oficina", "Laboratório de Informática 1")

        saida = self._rodar(
            "Laboratório de Informática", "Lab. de Informática", aplicar=True
        )

        atividade.refresh_from_db()
        self.assertEqual(atividade.local, "Lab. de Informática")
        # O setting continua canonicalizando para o nome antigo: o comando avisa.
        self.assertIn("AGENDA_ALIASES_LOCAL", saida)

    def test_nao_casa_parcial(self):
        atividade = self._atividade("Abertura", "Auditório 2")

        self._rodar("Auditório", "Auditório Nobre", aplicar=True)

        atividade.refresh_from_db()
        self.assertEqual(atividade.local, "Auditório 2")

    def test_dry_run_nao_grava(self):
        atividade = self._atividade("Abertura", "Auditório")

        saida = self._rodar("Auditório", "Auditório Nobre")

        atividade.refresh_from_db()
        self.assertEqual(atividade.local, "Auditório")
        self.assertIn("seria(m) atualizada(s)", saida)
        self.assertIn("Abertura", saida)

    def test_escopo_por_evento(self):
        dentro = self._atividade("Dentro", "Auditório")
        fora = self._atividade("Fora", "Auditório", evento=self.outro)

        self._rodar("Auditório", "Auditório Nobre", evento=self.evento, aplicar=True)

        dentro.refresh_from_db()
        fora.refresh_from_db()
        self.assertEqual(dentro.local, "Auditório Nobre")
        self.assertEqual(fora.local, "Auditório")

    def test_remove_repeticao_quando_o_novo_nome_ja_esta_na_lista(self):
        atividade = self._atividade("Abertura", "Auditório, Auditório Nobre")

        self._rodar("Auditório", "Auditório Nobre", aplicar=True)

        atividade.refresh_from_db()
        self.assertEqual(atividade.local, "Auditório Nobre")

    def test_nomes_iguais_recusa(self):
        with self.assertRaises(CommandError):
            self._rodar("Auditório", "auditorio", aplicar=True)

    def test_reporta_quando_nao_ha_nada_a_fazer(self):
        self._atividade("Abertura", "Sala de aula")

        saida = self._rodar("Auditório", "Auditório Nobre", aplicar=True)

        self.assertIn("Nada a fazer", saida)


class CatalogoNaTelaTests(TestCase):
    """Busca no catálogo, admin dos modelos novos e o select sem opção vazia."""

    def setUp(self):
        self.org = U.objects.create_user(
            email="org_cat@example.com", password=SENHA, cpf="12345678909",
            is_organizador=True,
        )
        hoje = timezone.localdate()
        self.evento = Evento.objects.create(
            title="Evento do Catálogo", description="d", local="Campus",
            data_inicio=hoje + timedelta(days=10), data_fim=hoje + timedelta(days=12),
            organizador=self.org,
        )
        self.client.force_login(self.org)

    def _criar_espacos(self, quantidade):
        for indice in range(quantidade):
            Espaco.objects.create(nome=f"Espaço {indice:02d}", capacidade=10)

    def _html_chamada(self):
        return self.client.get(
            reverse("organizador:chamada_proposicoes", args=[self.evento.id])
        ).content.decode()

    def test_busca_aparece_quando_a_lista_e_longa(self):
        self._criar_espacos(8)

        html = self._html_chamada()

        self.assertIn("data-busca-lista", html)
        self.assertIn('placeholder="Buscar espaço pelo nome"', html)
        self.assertIn('data-busca-item', html)
        self.assertIn("data-busca-vazio", html)

    def test_busca_nao_aparece_com_poucos_espacos(self):
        self._criar_espacos(3)

        html = self._html_chamada()

        # A lista continua com o gancho de busca, mas sem input nem aviso.
        self.assertIn("data-busca-lista", html)
        self.assertIn('data-busca-item', html)
        self.assertNotIn("data-busca-vazio", html)
        self.assertNotIn('placeholder="Buscar espaço pelo nome"', html)

    def test_modelos_do_catalogo_estao_no_admin(self):
        for modelo in (Espaco, ChamadaProposicoes, Vaga):
            with self.subTest(modelo=modelo.__name__):
                self.assertTrue(admin.site.is_registered(modelo))

    def test_select_de_espaco_sem_opcao_vazia(self):
        Espaco.objects.create(nome="Auditório", capacidade=40)

        form = VagaForm(evento=self.evento)

        self.assertIsNone(form.fields["espaco"].empty_label)
        self.assertNotIn('<option value="">', str(form["espaco"]))
