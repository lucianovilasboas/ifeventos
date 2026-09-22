"""RF-15 - Contrato da API REST. Fonte: API.md:14-64 (auth, convencoes) e 83-147."""

from datetime import date

from .base import API, RequisitosTestCase


class AutenticacaoTests(RequisitosTestCase):
    """API.md:14-50 - token/sessao, login por e-mail, 403 (nunca 401)."""

    def test_T_AP01_sem_token_devolve_403_e_sem_www_authenticate(self):
        self.requisito("RF-15", "API.md:49-50")
        r = self.client.get(f"{API}/meu-perfil/")
        self.assertEqual(r.status_code, 403, "API.md:49-50: sem token valido -> 403")
        self.assertNotIn("WWW-Authenticate", dict(r.headers), "API.md:50")

    def test_T_AP02_login_e_por_email_e_devolve_token(self):
        self.requisito("RF-15", "API.md:23-34")
        u = self.participante("login-email@req.test")
        r = self.api("post", f"{API}/auth/token/", {"email": u.email, "password": "senha-errada"})
        self.assertIn(r.status_code, (400, 401), "senha errada nao pode autenticar")
        r = self.api("post", f"{API}/auth/token/", {"email": u.email, "password": "SenhaReq123!"})
        self.assertEqual(r.status_code, 200, f"login por e-mail deve funcionar: {r.content[:200]}")
        self.assertIn("token", r.json())

    def test_T_AP03_registro_valida_cpf_e_tamanho_de_senha(self):
        self.requisito("RF-15", "API.md:36-38")
        r = self.api("post", f"{API}/auth/registro/", {"email": "novo@req.test", "password": "123", "cpf": ""})
        self.assertEqual(r.status_code, 400, "senha <6 e cpf ausente devem ser recusados")
        corpo = r.json()
        self.assertTrue(corpo, "erro de validacao deve vir por campo (API.md:63-64)")


class ConvencoesTests(RequisitosTestCase):
    """API.md:52-64 - paginacao 50, busca nos campos, filtros, envelope."""

    def test_T_AP04_envelope_de_listagem(self):
        self.requisito("RF-15", "API.md:52-54")
        r = self.api("get", f"{API}/eventos/")
        self.assertEqual(r.status_code, 200, "leitura anonima do catalogo (API.md:68)")
        for chave in ("count", "next", "previous", "results"):
            self.assertIn(chave, r.json(), f"envelope deve ter {chave}")

    def test_T_AP05_paginacao_de_50(self):
        self.requisito("RF-15", "API.md:52-54")
        u = self.dono()
        for i in range(55):
            self.evento(u, title=f"Evento {i:02d}")
        r = self.api("get", f"{API}/eventos/?page=1")
        corpo = r.json()
        self.assertEqual(corpo["count"], 55)
        self.assertEqual(len(corpo["results"]), 50, "50 por pagina")
        self.assertIsNotNone(corpo["next"], "deve haver proxima pagina")
        r2 = self.api("get", f"{API}/eventos/?page=2")
        self.assertEqual(len(r2.json()["results"]), 5)

    def test_T_AP06_busca_de_eventos_por_titulo_descricao_e_local(self):
        self.requisito("RF-15", "API.md:56-58")
        u = self.dono()
        self.evento(u, title="Zebra Alfa", description="x", local="y")
        self.evento(u, title="Comum", description="contem gamba na descricao", local="y")
        self.evento(u, title="Comum", description="x", local="Sala dos Tucanos")
        for termo, esperado in (("Zebra", 1), ("gamba", 1), ("Tucanos", 1)):
            r = self.api("get", f"{API}/eventos/?search={termo}")
            self.assertEqual(r.status_code, 200, f"search={termo} nao pode dar erro")
            self.assertEqual(r.json()["count"], esperado, f"busca por {termo} (API.md:56-58)")

    def test_T_AP07_busca_de_atividades_tambem_deve_filtrar(self):
        self.requisito("RF-15", "API.md:56-58")
        u = self.dono()
        e = self.evento(u)
        self.atividade(e, titulo="Oficina de Robotica")
        self.atividade(e, titulo="Palestra de Historia")
        r = self.api("get", f"{API}/atividades/?search=Robotica")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.json()["count"], 1,
            "API.md:56-58 documenta busca em atividades (titulo, descricao); "
            "parametro aceito e ignorado em silencio e contrato mentiroso",
        )


class EscritaContratoTests(RequisitosTestCase):
    """API.md:61-64, 113-116, 128-130 - ISO 8601, idempotencia, validacao por campo."""

    def test_T_AP08_criar_atividade_aceita_iso_com_e_sem_offset(self):
        self.requisito("RF-15", "API.md:61-62")
        u = self.dono()
        e = self.evento(u)
        tk = self.token(u)
        base = {"evento": e.id, "titulo": "Atividade ISO", "descricao": "d",
                "local": "Sala 1", "n_vagas": 5}
        com_offset = dict(base, data_hora_inicio="2026-10-10T14:00:00-03:00",
                          data_hora_fim="2026-10-10T15:00:00-03:00")
        r = self.api("post", f"{API}/atividades/", com_offset, token=tk)
        self.assertEqual(r.status_code, 201, f"ISO com offset deve ser aceito: {r.content[:250]}")
        sem_offset = dict(base, titulo="Atividade ISO 2",
                          data_hora_inicio="2026-10-11T14:00:00", data_hora_fim="2026-10-11T15:00:00")
        r2 = self.api("post", f"{API}/atividades/", sem_offset, token=tk)
        self.assertEqual(r2.status_code, 201, "ISO sem offset (fuso do sistema) deve ser aceito")

    def test_T_AP09_criar_evento_sem_campos_obrigatorios_responde_por_campo(self):
        self.requisito("RF-15", "API.md:63-64")
        u = self.dono()
        r = self.api("post", f"{API}/eventos/", {}, token=self.token(u))
        self.assertEqual(r.status_code, 400, "sem campos obrigatorios -> 400")
        self.assertIsInstance(r.json(), dict, "erro de validacao vem por campo, nao 'detail'")

    def test_T_AP10_palestrante_e_idempotente_por_email(self):
        self.requisito("RF-15", "API.md:113-116")
        u = self.dono()
        tk = self.token(u)
        corpo = {"email": "palestrante-repetido@req.test", "first_name": "Ana",
                 "last_name": "Silva", "cpf": "39053344705"}
        r1 = self.api("post", f"{API}/palestrantes/", corpo, token=tk)
        self.assertIn(r1.status_code, (200, 201), f"primeiro POST: {r1.content[:200]}")
        r2 = self.api("post", f"{API}/palestrantes/", corpo, token=tk)
        self.assertEqual(r2.status_code, 200, "repetir o mesmo e-mail devolve 200 (idempotente)")
        r3 = self.api("get", f"{API}/palestrantes/?search=palestrante-repetido", token=tk)
        self.assertEqual(r3.json()["count"], 1, "nao pode duplicar a conta")


class DocumentacaoVivaTests(RequisitosTestCase):
    """RF-24 (parte) - contrato self-describing cobre o que API.md promete."""

    def test_T_AP11_docs_e_schema_abrem_para_anonimo(self):
        self.requisito("RF-15", "API.md:10-12")
        for caminho in (f"{API}/schema/", f"{API}/docs/", f"{API}/redoc/"):
            r = self.api("get", caminho)
            self.assertEqual(r.status_code, 200, f"{caminho} deve abrir")

    def test_T_AP12_todas_as_rotas_documentadas_existem(self):
        self.requisito("RF-24", "API.md:83-183")
        u = self.dono()
        e = self.evento(u)
        a = self.atividade(e)
        self.chamada(e)          # BACKLOG.md:44-45: sem chamada a rota devolve 404 de regra
        tk = self.token(u)
        rotas = [
            "/eventos/", f"/eventos/{e.id}/", f"/eventos/{e.id}/chamada/",
            f"/eventos/{e.id}/painel-chamada/", f"/eventos/{e.id}/vagas/gerar/",
            f"/eventos/{e.id}/crachas.pdf", "/tipos-atividade/", "/palestrantes/",
            "/atividades/", f"/atividades/{a.id}/", f"/atividades/{a.id}/qrcode/",
            f"/atividades/{a.id}/qrcode.png", "/minhas-inscricoes/", "/meus-certificados/",
            "/meus-crachas/", f"/meus-crachas/{e.id}/qr.png", "/presencas/", "/espacos/",
            "/vagas/", "/propostas/", "/meu-perfil/", "/metadados/",
        ]
        faltando = []
        for rota in rotas:
            r = self.api("get", f"{API}{rota}", token=tk)
            if r.status_code == 405:
                r = self.api("post", f"{API}{rota}", {}, token=tk)   # rota existe, muda o metodo
            if r.status_code == 404:
                faltando.append(rota)
        self.assertEqual(
            faltando, [],
            "API.md documenta essas rotas; as que devolvem 404 nao existem no produto",
        )
