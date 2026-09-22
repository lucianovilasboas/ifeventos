"""RF-10 - Chamada de proposicoes: janela, grade de vagas, proposta e decisao.

Fontes: API.md:149-243 (contrato e comportamento documentado) e BACKLOG.md:114-119.
"""

from datetime import datetime
from datetime import timezone as tz

from django.test import override_settings

from .base import API, RequisitosTestCase

JANELA = {"inicio": "2026-09-01T00:00:00-03:00", "fim": "2026-12-31T23:59:00-03:00", "aberta": True}


class _BaseChamada(RequisitosTestCase):
    def setUp(self):
        self.u = self.dono("dono-chamada@req.test")
        self.e = self.evento(self.u, title="Evento da Chamada")
        self.tk = self.token(self.u)
        self.tp = self.tipo("Oficina")
        self.esp = self.espaco("Sala Chamada", capacidade=40)

    def abrir(self, aberta=True, janela=None):
        corpo = dict(janela or JANELA, aberta=aberta)
        return self.api("put", f"{API}/eventos/{self.e.id}/chamada/", corpo, token=self.tk)

    def proposta(self, vaga_id, usuario=None, **extra):
        corpo = {"vaga": vaga_id, "titulo": "Proposta Req", "descricao": "d",
                 "tipo": self.tp.id, "n_vagas": 5}
        corpo.update(extra)
        return self.api("post", f"{API}/propostas/", corpo,
                        token=self.token(usuario or self.u))


class JanelaTests(_BaseChamada):
    def test_T_CH01_abrir_e_fechar_a_janela(self):
        self.requisito("RF-10", "API.md:211-213, 236")
        r = self.abrir(True)
        self.assertEqual(r.status_code, 200, f"organizador dono abre a janela: {r.content[:200]}")
        d = self.api("get", f"{API}/eventos/{self.e.id}/chamada/", token=self.tk).json()
        self.assertTrue(d.get("aberta_agora"), "janela vigente deve estar aberta_agora=True")
        self.abrir(False)
        d2 = self.api("get", f"{API}/eventos/{self.e.id}/chamada/", token=self.tk).json()
        self.assertFalse(d2.get("aberta_agora"), "janela fechada nao pode aceitar propostas")

    def test_T_CH02_janela_vencida_nao_esta_aberta(self):
        self.requisito("RF-10", "API.md:236")
        self.abrir(True, {"inicio": "2026-01-01T00:00:00-03:00",
                          "fim": "2026-02-01T23:59:00-03:00"})
        d = self.api("get", f"{API}/eventos/{self.e.id}/chamada/", token=self.tk).json()
        self.assertFalse(d.get("aberta_agora"),
                         "janela no passado nao pode estar vigente mesmo com aberta=true")

    def test_T_CH03_organizador_sem_vinculo_nao_abre_a_janela(self):
        self.requisito("RF-11", "CHANGELOG.md:8-24")
        outro = self.dono("org-sem-vinculo-chamada@req.test")
        r = self.api("put", f"{API}/eventos/{self.e.id}/chamada/", JANELA, token=self.token(outro))
        self.assertNotEqual(r.status_code, 200, "so quem gerencia o evento abre a janela")


class GradeDeVagasTests(_BaseChamada):
    def gerar(self, **extra):
        corpo = {"dias": ["2026-10-10"], "blocos": ["08:00-10:00"],
                 "espacos": [self.esp.id], "capacidade": 30}
        corpo.update(extra)
        return self.api("post", f"{API}/eventos/{self.e.id}/vagas/gerar/", corpo, token=self.tk)

    def test_T_CH04_geracao_em_lote_e_idempotente(self):
        self.requisito("RF-10", "API.md:215-218")
        r1 = self.gerar()
        self.assertIn(r1.status_code, (200, 201), f"gerar grade: {r1.content[:200]}")
        d1 = r1.json()
        self.assertGreater(d1.get("criadas", 0), 0, "primeira rodada deve criar vagas")
        r2 = self.gerar()
        d2 = r2.json()
        self.assertEqual(d2.get("criadas", -1), 0, "segunda rodada nao pode duplicar a grade")

    def test_T_CH05_geracao_com_capacidade_omitida_nao_pode_nascer_com_1(self):
        self.requisito("RF-10", "API.md:157-158, 215-218")
        corpo = {"dias": ["2026-10-10"], "blocos": ["08:00-10:00"], "espacos": [self.esp.id]}
        r = self.api("post", f"{API}/eventos/{self.e.id}/vagas/gerar/", corpo, token=self.tk)
        self.assertIn(r.status_code, (200, 201), f"gerar sem 'capacidade': {r.content[:200]}")
        vagas = self.api("get", f"{API}/vagas/?evento={self.e.id}", token=self.tk).json()["results"]
        self.assertTrue(vagas, f"deve ter criado vaga: {r.content[:200]}")
        capacidades = sorted({v.get("capacidade") for v in vagas})
        self.assertNotEqual(capacidades, [1],
                            "Espaco.capacidade e a 'capacidade sugerida' (API.md:157); "
                            "vagas nascendo com 1 e provavel default do modelo")

    def test_T_CH06_vaga_fora_do_periodo_do_evento_e_recusada(self):
        self.requisito("RF-10", "API.md:168-169")
        corpo = {"evento": self.e.id, "espaco": self.esp.id,
                 "inicio": "2026-11-20T08:00:00-03:00", "fim": "2026-11-20T10:00:00-03:00",
                 "capacidade": 10}
        r = self.api("post", f"{API}/vagas/", corpo, token=self.tk)
        self.assertEqual(r.status_code, 400, "janela da vaga tem de estar no periodo do evento")

    def test_T_CH07_vaga_duplicada_espaco_mais_janela_e_recusada(self):
        self.requisito("RF-10", "API.md:168-169")
        corpo = {"evento": self.e.id, "espaco": self.esp.id,
                 "inicio": "2026-10-10T08:00:00-03:00", "fim": "2026-10-10T10:00:00-03:00",
                 "capacidade": 10}
        r1 = self.api("post", f"{API}/vagas/", corpo, token=self.tk)
        self.assertIn(r1.status_code, (200, 201), f"primeira vaga: {r1.content[:200]}")
        r2 = self.api("post", f"{API}/vagas/", corpo, token=self.tk)
        self.assertEqual(r2.status_code, 400, "mesmo espaco + mesma janela nao pode duplicar")


class PropostaTests(_BaseChamada):
    def setUp(self):
        super().setUp()
        self.abrir(True)
        self.v1 = self.vaga(self.e, self.esp)
        self.v2 = self.vaga(self.e, self.esp,
                            datetime(2026, 10, 10, 14, 0, tzinfo=tz.utc),
                            datetime(2026, 10, 10, 16, 0, tzinfo=tz.utc))

    def test_T_CH08_propor_com_janela_fechada_e_recusado(self):
        self.requisito("RF-10", "API.md:236")
        self.abrir(False)
        r = self.proposta(self.v1.id)
        self.assertEqual(r.status_code, 400, "propor exige janela aberta (checagem no servidor)")

    def test_T_CH09_propor_sem_tipo_e_recusado(self):
        self.requisito("RF-10", "API.md:200-202")
        r = self.api("post", f"{API}/propostas/",
                     {"vaga": self.v1.id, "titulo": "Sem tipo", "descricao": "d", "n_vagas": 5},
                     token=self.tk)
        self.assertEqual(r.status_code, 400, "`tipo` e obrigatorio na criacao (API.md:200)")

    def test_T_CH10_segunda_proposta_na_mesma_vaga_e_recusada(self):
        self.requisito("RF-10", "API.md:236-241")
        self.assertEqual(self.proposta(self.v1.id).status_code, 201, "primeira proposta")
        outra = self.participante("segundo-proponente@req.test")
        r2 = self.proposta(self.v1.id, usuario=outra)
        self.assertEqual(r2.status_code, 400, "vaga ja reservada: quem propoe primeiro leva")

    def test_T_CH11_proposta_pendente_ocupa_a_vaga_e_vaga_livre_lista_o_resto(self):
        self.requisito("RF-10", "BACKLOG.md:114-119")
        self.proposta(self.v1.id)
        d = self.api("get", f"{API}/eventos/{self.e.id}/chamada/", token=self.tk).json()
        livres = [v["id"] for v in d.get("vagas_livres", [])]
        self.assertNotIn(self.v1.id, livres, "vaga com proposta pendente nao esta livre")
        self.assertIn(self.v2.id, livres, "a outra vaga continua livre")

    def test_T_CH12_rejeitar_libera_a_vaga(self):
        self.requisito("RF-10", "API.md:241-242")
        prop = self.proposta(self.v1.id).json()
        pid = prop.get("id") or prop.get("atividade") or prop.get("atividade_id")
        self.assertIsNotNone(pid, f"POST /propostas/ deve devolver o id criado: {prop}")
        r = self.api("post", f"{API}/propostas/{pid}/rejeitar/", {"motivo": "Fora do tema"}, token=self.tk)
        self.assertIn(r.status_code, (200, 204), f"rejeitar: {r.content[:200]}")
        d = self.api("get", f"{API}/eventos/{self.e.id}/chamada/", token=self.tk).json()
        livres = [v["id"] for v in d.get("vagas_livres", [])]
        self.assertIn(self.v1.id, livres, "rejeitar libera a vaga sozinho (API.md:241)")

    def test_T_CH13_rejeitar_sem_motivo_e_recusado(self):
        self.requisito("RF-10", "API.md:202")
        prop = self.proposta(self.v1.id).json()
        pid = prop.get("id") or prop.get("atividade") or prop.get("atividade_id")
        r = self.api("post", f"{API}/propostas/{pid}/rejeitar/", {}, token=self.tk)
        self.assertEqual(r.status_code, 400, "rejeitar exige motivo")

    def test_T_CH14_aprovar_publica_na_programacao_e_aprovar_de_novo_e_recusado(self):
        self.requisito("RF-10", "API.md:200-202")
        prop = self.proposta(self.v1.id, titulo="Proposta Aprovada").json()
        pid = prop.get("id") or prop.get("atividade") or prop.get("atividade_id")
        r = self.api("post", f"{API}/propostas/{pid}/aprovar/", {"publicar": True}, token=self.tk)
        self.assertIn(r.status_code, (200, 204), f"aprovar: {r.content[:200]}")
        anon = self.api("get", f"{API}/atividades/?search=Proposta Aprovada").json()
        self.assertEqual(anon["count"], 1, "aprovada com publicar=true entra na programacao publica")
        r2 = self.api("post", f"{API}/propostas/{pid}/aprovar/", {"publicar": True}, token=self.tk)
        self.assertEqual(r2.status_code, 400, "proposta ja decidida nao pode ser decidida de novo")

    def test_T_CH15_aprovar_sem_publicar_mantem_fora_do_publico(self):
        self.requisito("RF-10", "API.md:200-202")
        prop = self.proposta(self.v1.id, titulo="Proposta Interna").json()
        pid = prop.get("id") or prop.get("atividade") or prop.get("atividade_id")
        self.api("post", f"{API}/propostas/{pid}/aprovar/", {"publicar": False}, token=self.tk)
        anon = self.api("get", f"{API}/atividades/?search=Proposta Interna").json()
        self.assertEqual(anon["count"], 0, "publicar=false nao pode vazar para o publico")

    def test_T_CH16_autor_e_organizador_do_evento_editam(self):
        """Decisao 4-b: o autor edita (pendente + chamada aberta) E o organizador do evento tambem."""
        self.requisito("RF-10", "API.md:178")
        autor = self.participante("autor@req.test")
        prop = self.proposta(self.v1.id, usuario=autor).json()
        pid = prop.get("id") or prop.get("atividade") or prop.get("atividade_id")

        # (i) o autor edita a propria proposta
        r = self.api("patch", f"{API}/propostas/{pid}/", {"titulo": "Editada pelo autor"},
                     token=self.token(autor))
        self.assertEqual(r.status_code, 200, f"autor edita a propria proposta: {r.content[:200]}")

        # (ii) o organizador do evento (dono) tambem edita — comportamento documentado
        r = self.api("patch", f"{API}/propostas/{pid}/", {"titulo": "Editada pelo organizador"},
                     token=self.tk)
        self.assertEqual(r.status_code, 200, f"organizador do evento edita: {r.content[:200]}")

        # (iii) quem nao e autor nem organiza nao edita
        terceiro = self.participante("terceiro-edicao@req.test")
        r = self.api("patch", f"{API}/propostas/{pid}/", {"titulo": "Invadida"},
                     token=self.token(terceiro))
        self.assertIn(r.status_code, (403, 404),
                      f"nao-autor e nao-organizador nao edita: {r.status_code}")

    def test_T_CH16b_organizador_sem_vinculo_nao_edita_proposta(self):
        self.requisito("RF-11", "CHANGELOG.md:8-24")
        autor = self.participante("autor-b@req.test")
        prop = self.proposta(self.v1.id, usuario=autor).json()
        pid = prop.get("id") or prop.get("atividade") or prop.get("atividade_id")
        intruso = self.dono("org-sem-vinculo-edicao@req.test")
        r = self.api("patch", f"{API}/propostas/{pid}/", {"titulo": "Invadida"},
                     token=self.token(intruso))
        self.assertIn(r.status_code, (403, 404),
                      f"organizador sem vinculo nao edita proposta alheia: {r.status_code}")
        from eventos.models import Atividade
        titulo_depois = Atividade.objects.filter(pk=pid).values_list("titulo", flat=True).first()
        self.assertNotEqual(titulo_depois, "Invadida", "nada pode ter sido gravado")

    @override_settings(MAX_PROPOSTAS_POR_PROPONENTE=1)
    def test_T_CH17_limite_de_propostas_por_pessoa(self):
        self.requisito("RF-10", "API.md:238")
        r1 = self.proposta(self.v1.id)
        self.assertEqual(r1.status_code, 201, "primeira proposta dentro do limite")
        r2 = self.proposta(self.v2.id)
        self.assertEqual(r2.status_code, 400,
                         "com MAX_PROPOSTAS_POR_PROPONENTE=1 a segunda proposta deve ser recusada")

    def test_T_CH18_vaga_com_proposta_ativa_trava_espaco_e_horario(self):
        self.requisito("RF-10", "API.md:168-170")
        self.proposta(self.v1.id)
        outro_esp = self.espaco("Sala Trava", capacidade=20)
        r_esp = self.api("patch", f"{API}/vagas/{self.v1.id}/", {"espaco": outro_esp.id}, token=self.tk)
        self.assertEqual(r_esp.status_code, 400, "espaco travado enquanto houver proposta ativa")
        r_cap = self.api("patch", f"{API}/vagas/{self.v1.id}/", {"capacidade": 33}, token=self.tk)
        self.assertIn(r_cap.status_code, (200, 204), "a capacidade ainda pode mudar")


class ContadoresTests(_BaseChamada):
    def test_T_CH19_vagas_livres_coerentes_entre_chamada_e_painel(self):
        self.requisito("RF-10", "API.md:221-229")
        self.abrir(True)
        v1 = self.vaga(self.e, self.esp)
        v2 = self.vaga(self.e, self.esp, datetime(2026, 10, 10, 14, 0, tzinfo=tz.utc),
                       datetime(2026, 10, 10, 16, 0, tzinfo=tz.utc))
        self.proposta(v1.id)
        chamada = self.api("get", f"{API}/eventos/{self.e.id}/chamada/", token=self.tk).json()
        painel = self.api("get", f"{API}/eventos/{self.e.id}/painel-chamada/", token=self.tk)
        self.assertEqual(painel.status_code, 200, "painel da chamada deve abrir para o dono")
        dados_painel = painel.json()
        ids_chamada = sorted(v["id"] for v in chamada.get("vagas_livres", []))
        ids_painel = sorted(v["id"] for v in dados_painel.get("vagas_livres", []))
        self.assertEqual(
            ids_chamada, ids_painel,
            "as duas leituras publicas de 'vagas livres' tem de concordar (invariante entre telas)",
        )
        self.assertEqual(ids_chamada, [v2.id], "so a vaga sem proposta ativa esta livre")
