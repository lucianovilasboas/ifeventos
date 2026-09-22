"""RF-06/RF-07 - Inscricao, limite de vagas e presenca/check-in.

Fontes: API.md:132-147 (endpoints e 3 formas de check-in), README.md:3-10.
"""

from datetime import datetime, timedelta
from datetime import timezone as tz

from eventos.models import Inscricao

from .base import API, RequisitosTestCase


class _BaseInscricao(RequisitosTestCase):
    def setUp(self):
        self.u = self.dono("dono-insc@req.test")
        self.e = self.evento(self.u)
        self.tp = self.tipo("Minicurso")
        self.a1 = self.atividade(self.e, titulo="Com 1 vaga", n_vagas=1, tipo=self.tp)
        self.p1 = self.participante("p1@req.test")
        self.p2 = self.participante("p2@req.test")
        self.tk1, self.tk2 = self.token(self.p1), self.token(self.p2)

    def inscrever(self, tk, atividade=None):
        return self.api("post", f"{API}/minhas-inscricoes/",
                        {"atividade": (atividade or self.a1).id}, token=tk)

    def minhas(self, tk):
        return self.api("get", f"{API}/minhas-inscricoes/", token=tk).json()


class LimiteDeVagasTests(_BaseInscricao):
    def test_T_I01_ultima_vaga_nao_pode_ser_vendida_duas_vezes(self):
        self.requisito("RF-06", "API.md:132-138")
        r1 = self.inscrever(self.tk1)
        self.assertIn(r1.status_code, (200, 201), f"primeira inscricao: {r1.content[:200]}")
        r2 = self.inscrever(self.tk2)
        self.assertEqual(
            r2.status_code, 400,
            f"atividade com n_vagas=1 aceitou a 2a pessoa (overselling): {r2.status_code} "
            f"{r2.content[:200]}",
        )

    def test_T_I02_nao_se_inscrever_duas_vezes_na_mesma_atividade(self):
        self.requisito("RF-06", "API.md:132-138")
        a = self.atividade(self.e, titulo="Dupla inscricao", n_vagas=10, tipo=self.tp)
        self.inscrever(self.tk1, a)
        r = self.inscrever(self.tk1, a)
        self.assertEqual(r.status_code, 400, "mesma pessoa nao se inscreve duas vezes")
        self.assertEqual(len(self.minhas(self.tk1)["results"]), 1)

    def test_T_I03_cancelar_libera_a_vaga(self):
        self.requisito("RF-06", "API.md:138")
        self.inscrever(self.tk1)
        ins = self.minhas(self.tk1)["results"][0]
        r = self.api("delete", f"{API}/minhas-inscricoes/{ins['id']}/", token=self.tk1)
        self.assertIn(r.status_code, (200, 204), f"cancelar: {r.status_code}")
        r2 = self.inscrever(self.tk2)
        self.assertIn(r2.status_code, (200, 201), "a vaga liberada deve aceitar outra pessoa")

    def test_T_I04_inscricao_de_terceiros_nao_aparece_para_mim(self):
        self.requisito("RF-06", "API.md:136")
        self.inscrever(self.tk1)
        self.assertNotIn("p2@req.test", self.api("get", f"{API}/minhas-inscricoes/",
                                                token=self.tk2).content.decode("utf-8", "ignore"))


class CheckinTests(_BaseInscricao):
    def setUp(self):
        super().setUp()
        self.a2 = self.atividade(self.e, titulo="Atividade Checkin", n_vagas=10, tipo=self.tp)
        self.inscricao = self.inscrever(self.tk1, self.a2).json()
        self.tk_org = self.token(self.u)

    def presencas(self):
        return self.api("get", f"{API}/presencas/?atividade={self.a2.id}", token=self.tk_org).json()

    def test_T_S01_checkin_manual_do_organizador(self):
        self.requisito("RF-07", "API.md:145-147")
        r = self.api("post", f"{API}/presencas/", {"atividade": self.a2.id, "participante": self.p1.id},
                     token=self.tk_org)
        self.assertIn(r.status_code, (200, 201), f"checkin manual: {r.content[:200]}")
        self.assertGreaterEqual(self.presencas().get("count", 0), 1, "presenca deve existir")

    def test_T_S02_checkin_repetido_nao_duplica_presenca(self):
        self.requisito("RF-07", "API.md:145-147")
        corpo = {"atividade": self.a2.id, "participante": self.p1.id}
        self.api("post", f"{API}/presencas/", corpo, token=self.tk_org)
        r2 = self.api("post", f"{API}/presencas/", corpo, token=self.tk_org)
        self.assertLess(r2.status_code, 500, "check-in repetido nao pode quebrar (unique por atividade+pessoa)")
        total = self.presencas().get("count", 0)
        self.assertEqual(total, 1, f"presenca duplicada: {total} registros")

    def _atividade_na_janela(self):
        """Atividade dentro da janela de confirmação.

        O QR/código da atividade é público, então só vale dentro da janela; a
        marcação manual ignora a janela de propósito (`registrar_presenca`).
        """
        agora = datetime.now(tz.utc)
        a = self.atividade(
            self.e, titulo="Checkin na janela", n_vagas=10, tipo=self.tp,
            data_hora_inicio=agora - timedelta(minutes=5),
            data_hora_fim=agora + timedelta(hours=1),
        )
        Inscricao.objects.create(atividade=a, participante=self.p1, confirmada=True)
        return a

    def _token_rotativo_da_atividade(self, atividade):
        """Token do QR da atividade pelo caminho publico — o que a tela exibe.

        Os UUIDs armazenados (`Atividade.codigo_confirmacao`) NAO sao o token:
        o valor valido e assinado e gerado por `gerar_token_atividade`.
        """
        qr = self.api("get", f"{API}/atividades/{atividade.id}/qrcode/", token=self.tk_org).json()
        return qr["url"].split("/p/")[-1].strip("/")

    def test_T_S03_checkin_por_token_da_atividade(self):
        self.requisito("RF-07", "API.md:145-147")
        a = self._atividade_na_janela()
        token_atividade = self._token_rotativo_da_atividade(a)
        r = self.api("post", f"{API}/presencas/", {"token_atividade": token_atividade}, token=self.tk1)
        self.assertIn(r.status_code, (200, 201),
                      f"a propria pessoa confirma pelo QR da atividade: {r.content[:200]}")

    def test_T_S03b_as_tres_formas_documentadas_de_checkin(self):
        """API.md:145-147: manual {atividade,participante}, codigo {atividade,codigo} e {token_atividade}."""
        self.requisito("RF-07", "API.md:145-147")
        a = self._atividade_na_janela()
        token_atividade = self._token_rotativo_da_atividade(a)
        crachas = self.api("get", f"{API}/meus-crachas/", token=self.tk1).json()
        codigo = next(c["codigo"] for c in crachas if c["evento_id"] == self.e.id)
        tentativas = {
            "token_atividade": (self.tk1, {"token_atividade": token_atividade}),
            "codigo": (self.tk_org, {"atividade": a.id, "codigo": codigo}),
            "manual": (self.tk_org, {"atividade": a.id, "participante": self.p1.id}),
        }
        resultado = {}
        for nome, (tk, corpo) in tentativas.items():
            r = self.api("post", f"{API}/presencas/", corpo, token=tk)
            resultado[nome] = (r.status_code, r.content.decode("utf-8", "ignore")[:120])
        funcionaram = [k for k, (s, _) in resultado.items() if s in (200, 201)]
        self.assertEqual(
            len(funcionaram), 3,
            f"API.md:145-147 documenta tres formas de check-in; devem funcionar: {resultado}",
        )

    def test_T_S04_organizador_sem_vinculo_nao_faz_checkin(self):
        self.requisito("RF-11", "CHANGELOG.md:8-24")
        intruso = self.dono("intruso-checkin@req.test")
        r = self.api("post", f"{API}/presencas/", {"atividade": self.a2.id, "participante": self.p1.id},
                     token=self.token(intruso))
        self.assertNotIn(r.status_code, (200, 201),
                         f"check-in em evento alheio: {r.status_code} {r.content[:160]}")

    def test_T_S05_participante_nao_marca_presenca_de_outro(self):
        self.requisito("RF-11", "API.md:142")
        r = self.api("post", f"{API}/presencas/", {"atividade": self.a2.id, "participante": self.p2.id},
                     token=self.tk1)
        self.assertNotIn(r.status_code, (200, 201),
                         f"participante marcou presenca de terceiro: {r.status_code}")
