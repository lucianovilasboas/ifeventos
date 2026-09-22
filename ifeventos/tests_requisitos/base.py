"""Base da suite por requisitos - IF Eventos (nossos eventos).

REGRAS DESTA SUITE (plano 2026-09-22, secao 5):
 1. URL LITERAL sempre - o caminho publico e o contrato. Nada de reverse("app:nome").
 2. A expectativa vem do REQUISITO documentado (README.md, API.md, CHANGELOG.md,
    BACKLOG.md), citado em cada caso e registrado por requisito().
 3. Assercao apenas sobre efeito observavel: status, JSON, HTML, contagem de estado.
 4. Falha aqui e EVIDENCIA, nao veredito. Classificar em BUG / LACUNA / AMBIGUIDADE /
    TESTE-ERRADO antes de reportar.

O setup (massa de teste) usa ORM - e o unico ponto que toca modelos; nenhuma
expectativa e derivada de models/serializers/views.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as tz

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from rest_framework.authtoken.models import Token

from eventos.models import (
    Atividade,
    Certificado,
    ChamadaProposicoes,
    Espaco,
    Evento,
    Inscricao,
    ParticipanteMetadados,
    TipoAtividade,
    Vaga,
)

U = get_user_model()
SENHA = "SenhaReq123!"

# Valores-canario: unicos, inconfundiveis. Se aparecerem numa resposta publica = vazamento.
CPF_CANARIO = "52998224725"
CPF_CANARIO_CRU = "529.982.247-25"
EMAIL_CANARIO = "pii-canario@exemplo-teste.invalid"
TEL_CANARIO = "31900001234"

API = "/api/v1"

# Requisitos exercitados nesta execucao: (RF, fonte, caso)
EXECUTADOS: list[tuple[str, str, str]] = []


class RequisitosTestCase(TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        """MEDIA_ROOT fixo em settings.py:517 -> redireciona para tmp: nenhum upload
        de teste pode cair na midia do ambiente de desenvolvimento."""
        import tempfile
        from pathlib import Path

        from django.test import override_settings

        cls._media_tmp = Path(tempfile.mkdtemp(prefix="media_req_"))
        cls.enterClassContext(override_settings(
            MEDIA_ROOT=cls._media_tmp,                      # Path, como no dev (settings.py:517)
            IA_ATIVA=False,                                 # nenhum teste chama provedor de IA
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",  # nenhum e-mail real
        ))
        super().setUpClass()

    def requisito(self, rf: str, fonte: str) -> None:
        EXECUTADOS.append((rf, fonte, self._testMethodName))

    # ---------------- massa de teste ----------------
    def usuario(self, email, **flags):
        dados = dict(email=email, password=SENHA, cpf="")
        dados.update(flags)
        return U.objects.create_user(**dados)

    def dono(self, email="dono@req.test"):
        return self.usuario(email, cpf=CPF_CANARIO, is_organizador=True)

    def participante(self, email="part@req.test"):
        return self.usuario(email, cpf="11144477735")

    def evento(self, organizador, **kwargs):
        dados = dict(
            title="Evento Req",
            description="descricao do evento",
            local="Auditorio",
            data_inicio=date(2026, 10, 10),
            data_fim=date(2026, 10, 12),
        )
        dados.update(kwargs)
        return Evento.objects.create(organizador=organizador, **dados)

    def atividade(self, evento, **kwargs):
        dados = dict(
            titulo="Atividade Req",
            descricao="descricao da atividade",
            local="Auditorio",
            data_hora_inicio=datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
            data_hora_fim=datetime(2026, 10, 10, 11, 0, tzinfo=tz.utc),
            n_vagas=10,
        )
        dados.update(kwargs)
        return Atividade.objects.create(evento=evento, **dados)

    def tipo(self, nome="Palestra"):
        return TipoAtividade.objects.create(nome=nome)

    def espaco(self, nome="Sala 1", capacidade=30):
        return Espaco.objects.create(nome=nome, capacidade=capacidade)

    def chamada(self, evento, aberta=True):
        return ChamadaProposicoes.objects.create(
            evento=evento,
            titulo="Chamada de proposicoes",
            inicio=datetime(2026, 10, 1, 0, 0, tzinfo=tz.utc),
            fim=datetime(2026, 10, 5, 23, 0, tzinfo=tz.utc),
            aberta=aberta,
        )

    def chamada_aberta(self, evento):
        """Chamada com janela contendo HOJE (setup, nao deriva expectativa)."""
        agora = datetime.now(tz.utc)
        return ChamadaProposicoes.objects.create(
            evento=evento,
            titulo="Chamada de proposicoes",
            inicio=agora - timedelta(days=1),
            fim=agora + timedelta(days=30),
            aberta=True,
        )

    def vaga(self, evento, espaco, inicio=None, fim=None, capacidade=1):
        return Vaga.objects.create(
            evento=evento,
            espaco=espaco,
            inicio=inicio or datetime(2026, 10, 10, 8, 0, tzinfo=tz.utc),
            fim=fim or datetime(2026, 10, 10, 10, 0, tzinfo=tz.utc),
            capacidade=capacidade,
        )

    # ---------------- cliente HTTP ----------------
    def token(self, user):
        return Token.objects.get_or_create(user=user)[0].key

    def logar(self, user, client=None):
        c = client or self.client
        c.force_login(user)
        return c

    def api(self, metodo, caminho, dados=None, token=None, cliente=None, **extra):
        c = cliente or self.client
        cabecalhos = dict(extra)
        if token:
            cabecalhos["HTTP_AUTHORIZATION"] = f"Token {token}"
        fn = getattr(c, metodo.lower())
        if metodo.upper() in ("POST", "PUT", "PATCH"):
            return fn(caminho, data=dados, content_type="application/json", **cabecalhos)
        return fn(caminho, **cabecalhos)

    # ---------------- observacao ----------------
    def contar(self, modelo):
        return modelo.objects.count()

    def trecho(self, resposta, alvo, janela=110):
        """Trecho do corpo em volta de um valor encontrado - evidencia da falha."""
        corpo = resposta.content.decode("utf-8", "ignore")
        i = corpo.find(alvo)
        if i < 0:
            return "(nao encontrado)"
        ini = max(0, i - janela // 2)
        return "..." + corpo[ini:i + janela] + "..."

    def vazamentos(self, resposta, extras=()):
        """Valores-canario encontrados no corpo da resposta (vazio = sem vazamento)."""
        corpo = resposta.content.decode("utf-8", "ignore")
        alvos = [CPF_CANARIO, CPF_CANARIO_CRU, EMAIL_CANARIO, TEL_CANARIO]
        alvos.extend(extras)
        return [a for a in alvos if a in corpo]
