"""RF-11 - Permissoes e escopo. Fontes: API.md:66-79, CHANGELOG.md:8-24 (2.3.0), 139-152 (2.2.2), 167-190 (2.2.0).

Regra vigente (2.3.0, mais recente que API.md/BACKLOG):
  * `pode_gerenciar_evento` = dono OU co-organizador; staff/superuser sempre.
  * `is_organizador` sozinha NAO da acesso a evento alheio.
  * Rotas de escrita do organizador: 403 para participante/equipe (2.2.2).
  * Equipe de apoio (`is_equipe` + `Evento.equipe`): so check-in/QR nos eventos vinculados.
"""

from .base import API, RequisitosTestCase

ROTAS_EVENTO = [
    ("get", "/organizador/atividades_evento/{e}/"),
    ("get", "/organizador/editar_evento/{e}/"),
    ("get", "/organizador/chamada/{e}/"),
    ("get", "/organizador/chamada/{e}/painel/"),
    ("get", "/organizador/propostas/{e}/"),
    ("get", "/organizador/relatorio_participantes/{e}/"),
    ("get", "/organizador/relatorios_graficos/{e}/"),
    ("get", "/organizador/ocupacao_salas/{e}/"),
    ("get", "/organizador/crachas/evento/{e}/"),
    ("get", "/organizador/evento/{e}/operacao/"),
    ("post", "/organizador/evento/{e}/divulgacao/"),
]
ROTAS_GLOBAIS = [
    ("get", "/organizador/dashboard/"),
    ("get", "/organizador/criar_evento/"),
    ("get", "/organizador/metadados/modelo.csv"),
]
RECUSA = (403, 404)   # 404 = recusa sem revelar existencia; tambem e recusa


class _BasePermissoes(RequisitosTestCase):
    def setUp(self):
        self.dono_u = self.dono("dono@req.test")
        self.evento_obj = self.evento(self.dono_u, title="Evento do Dono")
        self.atividade_obj = self.atividade(self.evento_obj, publicada=False)
        self.outro_dono = self.dono("outro-dono@req.test")
        self.evento_outro = self.evento(self.outro_dono, title="Evento Alheio")
        self.particip = self.participante("part@req.test")
        self.palestrante = self.usuario("palestrante@req.test", is_palestrante=True)
        self.equipe = self.usuario("equipe@req.test", is_equipe=True)
        self.evento_obj.equipe.add(self.equipe)
        self.equipe_outro = self.usuario("equipe-outro@req.test", is_equipe=True)
        self.evento_outro.equipe.add(self.equipe_outro)
        self.org_sem_vinculo = self.dono("org-sem-vinculo@req.test")
        self.coorg = self.dono("coorg@req.test")
        self.evento_obj.organizadores.add(self.coorg)
        self.superuser = self.usuario("super@req.test", is_superuser=True, is_staff=True)

    def rotas(self, e=None):
        e = e or self.evento_obj.id
        return [(m, r.format(e=e)) for m, r in ROTAS_EVENTO]

    def globais(self):
        return list(ROTAS_GLOBAIS)


class GestaoDoEventoTests(_BasePermissoes):
    def test_T_PE01_participante_e_palestrante_levam_403(self):
        self.requisito("RF-11", "CHANGELOG.md:139-152")
        for persona in (self.particip, self.palestrante):
            self.logar(persona)
            for metodo, rota in self.rotas():
                with self.subTest(persona=persona.email, rota=rota):
                    r = getattr(self.client, metodo)(rota)
                    self.assertIn(r.status_code, RECUSA, f"{persona.email} em {rota}")

    def test_T_PE02_equipe_de_apoio_nao_abre_gestao_da_organizacao(self):
        self.requisito("RF-11", "CHANGELOG.md:151-152")
        self.logar(self.equipe)
        for metodo, rota in self.rotas():
            with self.subTest(rota=rota):
                self.assertIn(getattr(self.client, metodo)(rota).status_code, RECUSA, rota)

    def test_T_PE03_organizador_sem_vinculo_nao_opera_evento_alheio(self):
        self.requisito("RF-11", "CHANGELOG.md:8-24")
        self.logar(self.org_sem_vinculo)
        abertas = []
        for metodo, rota in self.rotas():
            r = getattr(self.client, metodo)(rota)
            if r.status_code == 200:
                abertas.append(rota)
        self.assertEqual(
            abertas, [],
            "2.3.0: `is_organizador` sozinha nao da acesso a qualquer evento; "
            f"estas rotas abriram para organizador sem vinculo: {abertas}",
        )

    def test_T_PE04_dashboard_nao_lista_evento_alheio(self):
        self.requisito("RF-11", "CHANGELOG.md:8-24")
        self.logar(self.org_sem_vinculo)
        r = self.client.get("/organizador/dashboard/")
        self.assertEqual(r.status_code, 200, "dashboard do organizador deve abrir para ele")
        self.assertNotIn(
            "Evento do Dono", r.content.decode("utf-8", "ignore"),
            "organizador sem vinculo nao pode ver o evento de outro no dashboard",
        )

    def test_T_PE05_dono_e_coorganizador_gerenciam(self):
        self.requisito("RF-11", "CHANGELOG.md:8-24")
        for persona in (self.dono_u, self.coorg, self.superuser):
            self.logar(persona)
            for metodo, rota in self.rotas():
                with self.subTest(persona=persona.email, rota=rota):
                    self.assertEqual(getattr(self.client, metodo)(rota).status_code, 200,
                                     f"{persona.email} deveria gerenciar {rota}")

    def test_T_PE06_apenas_o_dono_exclui_o_evento(self):
        self.requisito("RF-11", "CHANGELOG.md:8-24")
        self.logar(self.coorg)
        r = self.client.post(f"/organizador/excluir_evento/{self.evento_obj.id}/")
        self.assertIn(r.status_code, (403, 404), "co-organizador nao exclui o evento (so o dono)")
        self.assertTrue(
            type(self.evento_obj).objects.filter(pk=self.evento_obj.id).exists(),
            "co-organizador nao pode ter apagado o evento",
        )

    def test_T_PE07_equipe_de_apoio_so_nos_eventos_vinculados(self):
        self.requisito("RF-11", "CHANGELOG.md:184-188")
        self.logar(self.equipe)
        self.assertEqual(self.client.get("/apoio/").status_code, 200,
                         "equipe deve abrir o proprio painel")
        self.assertEqual(self.client.get(f"/apoio/evento/{self.evento_obj.id}/").status_code, 200,
                         "equipe vinculada opera o evento dela")
        r = self.client.get(f"/apoio/evento/{self.evento_outro.id}/")
        self.assertEqual(r.status_code, 403, "equipe de outro evento nao faz check-in aqui")


class AcoesGlobaisTests(_BasePermissoes):
    def test_T_PE08_participante_nao_acessa_acoes_globais(self):
        self.requisito("RF-11", "CHANGELOG.md:144-150")
        self.logar(self.particip)
        falhas = []
        for metodo, rota in self.globais():
            r = getattr(self.client, metodo)(rota)
            if r.status_code != 403:
                falhas.append(f"{rota} -> {r.status_code} {r.headers.get('Location', '')}")
        self.assertEqual(falhas, [], "2.2.2: acoes globais exigem a flag de organizador (403)")

    def test_T_PE08b_dashboard_aberto_nao_pode_expor_eventos_de_terceiros(self):
        """Complemento do T_PE08: se a rota abrir, o corpo dela nao pode trazer dados alheios."""
        self.requisito("RF-11", "CHANGELOG.md:139-152")
        self.logar(self.particip)
        r = self.client.get("/organizador/dashboard/")
        corpo = r.content.decode("utf-8", "ignore")
        exposto = {
            "status": r.status_code,
            "titulo_de_evento_alheio": "Evento do Dono" in corpo,
            "pii": self.vazamentos(r),
        }
        self.assertEqual(
            exposto,
            {"status": 403, "titulo_de_evento_alheio": False, "pii": []},
            "dashboard do organizador nao e area de participante",
        )

    def test_T_PE09_participante_nao_cria_ou_exclui_atividade(self):
        self.requisito("RF-11", "CHANGELOG.md:141-143")
        self.logar(self.particip)
        self.client.post(f"/organizador/atividade/{self.atividade_obj.id}/publicar/")
        self.atividade_obj.refresh_from_db()
        self.assertFalse(self.atividade_obj.publicada, "participante nao pode publicar atividade")
        self.client.post(f"/organizador/excluir_atividade/{self.atividade_obj.id}/")
        self.assertTrue(
            type(self.atividade_obj).objects.filter(pk=self.atividade_obj.id).exists(),
            "participante nao pode excluir atividade",
        )

    def test_T_PE10_participante_nao_emite_certificado(self):
        self.requisito("RF-11", "CHANGELOG.md:147-148")
        from eventos.models import Certificado
        self.logar(self.particip)
        antes = Certificado.objects.count()
        self.client.post(f"/organizador/emitir-certificados/evento/{self.evento_obj.id}/")
        self.client.post(f"/organizador/emitir-certificados/atividade/{self.atividade_obj.id}/")
        self.assertEqual(Certificado.objects.count(), antes,
                         "emissao de certificado exige login + organizador (2.2.2)")

    def test_T_PE11_participante_nao_usa_endpoints_de_ia(self):
        self.requisito("RF-11", "CHANGELOG.md:149-150")
        self.logar(self.particip)
        for rota in ("/organizador/gerar_descricao/", "/organizador/sugerir_categoria/"):
            with self.subTest(rota=rota):
                self.assertEqual(self.client.post(rota).status_code, 403, rota)

    def test_T_PE12_participante_nao_cadastra_palestrante(self):
        self.requisito("RF-11", "CHANGELOG.md:145-146")
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.logar(self.particip)
        antes = U.objects.filter(email="novo-palestrante@req.test").count()
        self.client.post("/organizador/adicionar_palestrante/",
                         {"email": "novo-palestrante@req.test", "first_name": "X"})
        depois = U.objects.filter(email="novo-palestrante@req.test").count()
        self.assertEqual((antes, depois), (0, 0), "participante nao cria palestrante")


class PermissoesDaApiTests(_BasePermissoes):
    def test_T_PE13_api_bloqueia_dados_pessoais_e_operacao(self):
        self.requisito("RF-11", "API.md:75-77, 142")
        rotas = ["/meu-perfil/", "/palestrantes/", "/metadados/", "/presencas/", "/vagas/",
                 "/propostas/", "/minhas-inscricoes/"]
        for rota in rotas:
            with self.subTest(rota=rota):
                self.assertEqual(self.api("get", f"{API}{rota}").status_code, 403,
                                 f"anonimo em {rota}")

    def test_T_PE14_participante_nao_le_dados_pessoais_pela_api(self):
        self.requisito("RF-11", "API.md:75-77")
        tk = self.token(self.particip)
        # /vagas/ e GET "autenticado" em API.md:164 (ambigua com o escopo de 2.3.0) - fica em T_PE16.
        for rota in ("/palestrantes/", "/metadados/", "/presencas/"):
            with self.subTest(rota=rota):
                r = self.api("get", f"{API}{rota}", token=tk)
                self.assertEqual(r.status_code, 403,
                                 f"participante em {rota} (API.md:75-77,142): {r.status_code} "
                                 f"{r.content[:160]}")

    def test_T_PE14b_participante_nao_ve_presenca_de_terceiros(self):
        """API.md:142 - /presencas/ e leitura do organizador do evento."""
        self.requisito("RF-11", "API.md:142")
        from datetime import datetime
        from datetime import timezone as tz
        from eventos.models import Inscricao, Presenca
        ativ = self.atividade_obj
        terceiro = self.participante("terceiro-presenca@req.test")
        Inscricao.objects.create(atividade=ativ, participante=terceiro, confirmada=True)
        Presenca.objects.create(atividade=ativ, participante=terceiro,
                                registrada_em=datetime(2026, 10, 10, 10, 5, tzinfo=tz.utc))
        tk = self.token(self.particip)
        r = self.api("get", f"{API}/presencas/", token=tk)
        corpo = r.content.decode("utf-8", "ignore")
        problema = []
        if r.status_code != 403:
            problema.append(f"status={r.status_code}")
        if "terceiro-presenca" in corpo:
            problema.append("expoe presenca de terceiros")
        self.assertEqual(problema, [],
                         "participante nao pode listar presencas (API.md:142); "
                         f"resposta: {corpo[:220]}")

    def test_T_PE15_dono_le_o_que_gerencia(self):
        self.requisito("RF-11", "API.md:101, 111, 164")
        tk = self.token(self.dono_u)
        for rota in (f"/vagas/?evento={self.evento_obj.id}",
                     f"/eventos/{self.evento_obj.id}/painel-chamada/",
                     "/metadados/", "/palestrantes/"):
            with self.subTest(rota=rota):
                self.assertEqual(self.api("get", f"{API}{rota}", token=tk).status_code, 200, rota)

    def test_T_PE16_organizador_sem_vinculo_nao_gerencia_pela_api(self):
        self.requisito("RF-11", "CHANGELOG.md:8-24")
        tk = self.token(self.org_sem_vinculo)
        abertas = []
        for rota in (f"/eventos/{self.evento_obj.id}/painel-chamada/",
                     f"/vagas/?evento={self.evento_obj.id}"):
            if self.api("get", f"{API}{rota}", token=tk).status_code == 200:
                abertas.append(rota)
        self.assertEqual(abertas, [], f"organizador sem vinculo nao gerencia evento alheio: {abertas}")


class RedirecionamentoAnonimoTests(_BasePermissoes):
    def test_T_PE17_anonimo_e_mandado_para_login_no_site(self):
        self.requisito("RF-11", "README.md:7-8")
        for metodo, rota in self.rotas():
            with self.subTest(rota=rota):
                r = getattr(self.client, metodo)(rota)
                self.assertEqual(r.status_code, 302, f"anonimo em {rota}")
                self.assertIn("/accounts/login", r.headers.get("Location", ""))
