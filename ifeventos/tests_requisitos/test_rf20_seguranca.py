"""RF-20 - Seguranca e abuso. Fontes: setup/settings.py, README.md:217-222, API.md:14-50.

Nada aqui corrige o produto: cada caso so mede e produz evidencia.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from .base import API, RequisitosTestCase

XSS = "<script>alert('xss-requisitos')</script>"
XSS_IMG = "<img src=x onerror=alert(1)>"


class ForcaBrutaTests(RequisitosTestCase):
    def test_T_SE01_autenticacao_deve_limitar_tentativas(self):
        """settings.py nao configura throttle do DRF nem lockout: medir o efeito pratico."""
        self.requisito("RF-20", "API.md:27-34; setup/settings.py")
        u = self.participante("bruteforce@req.test")
        codigos = []
        for _ in range(10):
            r = self.api("post", f"{API}/auth/token/", {"email": u.email, "password": "errada"})
            codigos.append(r.status_code)
        correto = self.api("post", f"{API}/auth/token/", {"email": u.email, "password": "SenhaReq123!"})
        self.assertNotEqual(
            correto.status_code, 200,
            f"apos 10 falhas o login correto deveria estar bloqueado/limitado; "
            f"codigos das falhas={codigos}, login correto={correto.status_code}",
        )


class CsrfTests(RequisitosTestCase):
    def test_T_SE02_post_sem_csrf_token_e_recusado(self):
        self.requisito("RF-20", "README.md:79-80")
        u = self.dono()
        c = Client(enforce_csrf_checks=True)
        c.force_login(u)
        r = c.post("/organizador/criar_evento/", {"title": "Injetado", "description": "d",
                                                  "local": "x", "data_inicio": "2026-10-10",
                                                  "data_fim": "2026-10-11"})
        self.assertEqual(r.status_code, 403, "POST sem token CSRF deve ser recusado")


class EscapeXssTests(RequisitosTestCase):
    def setUp(self):
        self.u = self.dono()
        self.e = self.evento(self.u)

    def test_T_SE03_titulo_e_descricao_do_usuario_nao_viram_script(self):
        self.requisito("RF-20", "README.md:3-10")
        a = self.atividade(self.e, titulo=XSS, descricao=XSS_IMG, publicada=True)
        telas = {
            "programacao_publica": f"/eventos/programacao/{self.e.id}",
            "lista_de_eventos": "/eventos/",
        }
        self.logar(self.u)
        telas["atividades_do_organizador"] = f"/organizador/atividades_evento/{self.e.id}/"
        achados = {}
        for nome, rota in telas.items():
            r = self.client.get(rota)
            corpo = r.content.decode("utf-8", "ignore")
            cru = XSS in corpo or XSS_IMG in corpo
            escapado = "&lt;script&gt;" in corpo or "&lt;img" in corpo
            if cru:
                achados[nome] = {"cru": True, "escapado": escapado,
                                 "contexto": self.trecho(r, "<script>alert")}
        self.assertEqual(achados, {},
                         f"conteudo do usuario renderizado CRU (nao escapado): {achados}")

    def test_T_SE04_motivo_de_rejeicao_nao_viram_script_para_o_proponente(self):
        self.requisito("RF-20", "CHANGELOG.md:180-181")
        proponente = self.participante("proponente-xss@req.test")
        a = self.atividade(self.e, titulo="Proposta XSS", publicada=False, situacao="rejeitada",
                           motivo_rejeicao=XSS_IMG, proponente=proponente)
        self.logar(proponente)
        r = self.client.get("/participante/propostas/")
        corpo = r.content.decode("utf-8", "ignore")
        cru = XSS_IMG in corpo or XSS in corpo
        escapado = "&lt;img" in corpo or "&lt;script&gt;" in corpo
        self.assertFalse(
            cru and not escapado,
            f"motivo da rejeicao renderizado CRU ao proponente; contexto: {self.trecho(r, 'onerror')}",
        )
        self.assertIn(XSS_IMG.replace("<", "&lt;").replace(">", "&gt;") in corpo or XSS_IMG in corpo, (True, False),
                      "sonda registrada")


class UploadTests(RequisitosTestCase):
    def test_T_SE05_arquivo_que_nao_e_imagem_e_recusado_sem_500(self):
        self.requisito("RF-20", "eventos/imagens.py")
        u = self.dono()
        a = self.atividade(self.evento(u))
        tk = self.token(u)
        tentativas = {
            "svg_disfarcado": ("capa.svg", b"<svg onload=alert(1)></svg>", "image/svg+xml"),
            "texto_com_extensao_png": ("capa.png", b"isto nao e um png", "image/png"),
        }
        resultados = {}
        for nome, (arq, conteudo, tipo) in tentativas.items():
            up = SimpleUploadedFile(arq, conteudo, content_type=tipo)
            r = self.client.patch(f"{API}/atividades/{a.id}/", {"imagem": up},
                                  HTTP_AUTHORIZATION=f"Token {tk}")
            resultados[nome] = r.status_code
            self.assertLess(r.status_code, 500, f"{nome}: {r.status_code} {r.content[:200]}")
        self.assertTrue(all(400 <= s < 500 for s in resultados.values()),
                        f"arquivo invalido deve ser recusado com 4xx: {resultados}")


class IdorDownloadTests(RequisitosTestCase):
    def test_T_SE06_organizador_sem_vinculo_nao_baixa_artefatos_do_evento_alheio(self):
        self.requisito("RF-20", "CHANGELOG.md:8-24")
        dono = self.dono("dono-idor@req.test")
        e = self.evento(dono)
        self.atividade(e)
        intruso = self.dono("intruso-idor@req.test")
        tk = self.token(intruso)
        abertos = {}
        for rota in (f"/eventos/{e.id}/crachas.pdf", f"/eventos/{e.id}/painel-chamada/",
                     f"/eventos/{e.id}/vagas/gerar/", f"/eventos/{e.id}/chamada/"):
            r = self.api("get", f"{API}{rota}", token=tk)
            if r.status_code in (200, 201):
                abertos[rota] = r.status_code
            self.assertLess(r.status_code, 500, f"{rota} -> {r.status_code}")
        self.assertEqual(abertos, {}, f"artefatos de evento alheio acessiveis: {abertos}")


class CabecalhosTests(RequisitosTestCase):
    def test_T_SE07_cabecalhos_de_seguranca_no_site(self):
        self.requisito("RF-20", "README.md:217-222")
        r = self.client.get("/eventos/")
        faltando = [h for h in ("X-Content-Type-Options", "X-Frame-Options")
                    if h not in dict(r.headers)]
        self.assertEqual(faltando, [], f"cabecalhos ausentes: {faltando}")


class MediaRootConfiguravelTests(RequisitosTestCase):
    def test_T_SE09_media_root_como_string_nao_pode_quebrar_endpoint(self):
        """settings.py:517 fixa MEDIA_ROOT como Path; Django documenta MEDIA_ROOT como string.

        Com MEDIA_ROOT string (padrao do Django / via variavel de ambiente), o endpoint de
        crachas nao pode responder 500.
        """
        self.requisito("RF-18/RF-20", "setup/settings.py:517; CHANGELOG.md:192-205")
        import tempfile
        from django.test import override_settings
        u = self.dono("media-root@req.test")
        e = self.evento(u)
        self.atividade(e)
        self.logar(u)
        with override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="media_str_")):
            r = self.client.get(f"/organizador/crachas/evento/{e.id}/")
        self.assertLess(
            r.status_code, 500,
            f"MEDIA_ROOT como string derruba o endpoint de crachas: HTTP {r.status_code}",
        )


class AdminTests(RequisitosTestCase):
    def test_T_SE08_admin_nao_abre_para_participante(self):
        self.requisito("RF-21", "README.md:10")
        anon = self.client.get("/admin/")
        self.assertEqual(anon.status_code, 302, "anonimo no admin deve ir para o login")
        self.logar(self.participante("nao-staff@req.test"))
        logado = self.client.get("/admin/")
        self.assertNotEqual(logado.status_code, 200, "participante nao pode abrir o admin")
