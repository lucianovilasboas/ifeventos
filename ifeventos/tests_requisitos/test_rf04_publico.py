"""RF-04/RF-02 - catalogo publico e vazamento de PII/rasccunho. Fontes: API.md:66-79, BACKLOG.md:136."""

from .base import API, RequisitosTestCase


class CatalogoPublicoTests(RequisitosTestCase):
    def test_T_P01_rascunho_nao_aparece_para_anonimo(self):
        self.requisito("RF-04", "API.md:78-79")
        u = self.dono()
        e = self.evento(u)
        self.atividade(e, titulo="Publicada", publicada=True)
        self.atividade(e, titulo="Rascunho", publicada=False)
        r = self.api("get", f"{API}/atividades/")
        titulos = [a["titulo"] for a in r.json()["results"]]
        self.assertIn("Publicada", titulos)
        self.assertNotIn("Rascunho", titulos, "rascunho nao e catalogo publico (API.md:78-79)")

    def test_T_P02_proposta_pendente_nao_vaza_para_anonimo(self):
        self.requisito("RF-10", "BACKLOG.md:136")
        u = self.dono()
        e = self.evento(u)
        self.atividade(e, titulo="Proposta pendente", publicada=False, situacao="pendente")
        r = self.api("get", f"{API}/atividades/")
        self.assertNotIn("Proposta pendente", [a["titulo"] for a in r.json()["results"]])
        r2 = self.api("get", f"{API}/eventos/{e.id}/")
        corpo = r2.content.decode("utf-8", "ignore")
        self.assertNotIn(
            "Proposta pendente", corpo,
            "detalhe publico do evento expoe atividade NAO publicada (API.md:78-79, BACKLOG.md:136). "
            "Trecho: " + self.trecho(r2, "Proposta pendente"),
        )

    def test_T_P03_programacao_publica_esconde_rascunho(self):
        self.requisito("RF-04", "API.md:78-79")
        u = self.dono()
        e = self.evento(u)
        self.atividade(e, titulo="Atividade Visivel", publicada=True)
        self.atividade(e, titulo="Atividade Oculta", publicada=False)
        r = self.client.get(f"/eventos/programacao/{e.id}")
        self.assertEqual(r.status_code, 200, "programacao publica deve abrir")
        corpo = r.content.decode("utf-8", "ignore")
        self.assertIn("Atividade Visivel", corpo)
        self.assertNotIn("Atividade Oculta", corpo, "programacao publica nao mostra rascunho")

    def test_T_P04_busca_sem_resultado_nao_quebra(self):
        self.requisito("RF-04", "README.md:3-10")
        r = self.api("get", f"{API}/eventos/?search=zzz-nao-existe-zzz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 0)


class PiiTests(RequisitosTestCase):
    """Nenhuma leitura anonima pode expor CPF/e-mail/telefone (API.md:75-77)."""

    def test_T_P05_leituras_publicas_sem_pii(self):
        self.requisito("RF-11", "API.md:75-77")
        u = self.usuario("pii-canario@exemplo-teste.invalid", cpf="52998224725",
                         telefone="(31) 90000-1234", is_organizador=True)
        e = self.evento(u)
        self.atividade(e, titulo="Atividade PII")
        rotas = ["/eventos/", f"/eventos/{e.id}/", "/atividades/", "/tipos-atividade/",
                 "/espacos/", f"/eventos/{e.id}/chamada/"]
        achados = {}
        for rota in rotas:
            r = self.api("get", f"{API}{rota}")
            vaz = self.vazamentos(r)
            if vaz:
                achados[rota] = {v: self.trecho(r, v) for v in vaz}
        self.assertEqual(achados, {}, f"PII em leitura publica (API.md:75-77): {achados}")

    def test_T_P06_paginas_publicas_do_site_sem_pii(self):
        self.requisito("RF-11", "API.md:75-77")
        u = self.usuario("pii-canario@exemplo-teste.invalid", cpf="52998224725",
                         telefone="(31) 90000-1234", is_organizador=True)
        e = self.evento(u)
        self.atividade(e, titulo="Atividade PII site")
        achados = {}
        for rota in ["/eventos/", f"/eventos/programacao/{e.id}"]:
            r = self.client.get(rota)
            vaz = self.vazamentos(r)
            if vaz:
                achados[rota] = vaz
        self.assertEqual(achados, {}, f"PII em pagina publica: {achados}")

    def test_T_P07_verificacao_publica_com_token_invalido_nao_quebra(self):
        self.requisito("RF-08", "API.md:143")
        for rota in (f"{API}/verificar/token-invalido-requisitos/", "/c/token-invalido-requisitos/"):
            r = self.client.get(rota)
            self.assertLess(r.status_code, 500, f"{rota} nao pode devolver 5xx")
            self.assertNotEqual(r.status_code, 200, f"{rota} com token inexistente nao pode dar 200")


class ExportacoesPublicasTests(RequisitosTestCase):
    def test_T_P08_agenda_ics_do_evento(self):
        self.requisito("RF-04", "README.md:3-10")
        u = self.dono()
        e = self.evento(u)
        self.atividade(e, titulo="Atividade no ICS")
        r = self.client.get(f"/eventos/programacao/{e.id}/agenda.ics")
        self.assertEqual(r.status_code, 200, "agenda.ics deve existir")
        self.assertIn("calendar", r.headers.get("Content-Type", "").lower())
        self.assertIn("Atividade no ICS", r.content.decode("utf-8", "ignore"))

    def test_T_P09_pdf_da_programacao(self):
        self.requisito("RF-04", "README.md:3-10")
        u = self.dono()
        e = self.evento(u)
        self.atividade(e, titulo="Atividade no PDF")
        r = self.client.get(f"/eventos/programacao/{e.id}/programacao.pdf")
        self.assertEqual(r.status_code, 200, "PDF da programacao deve baixar")
        self.assertTrue(r.content.startswith(b"%PDF"), "conteudo deve ser PDF de verdade")
