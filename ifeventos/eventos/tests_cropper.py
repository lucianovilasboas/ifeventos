"""Testes dos fluxos de recorte de imagem (Cropper) dos formulários.

O recorte chega no POST como data URL base64 em `cropped_image`; a view deve
trocar o arquivo original por ele. Estes testes travam:

  * o arquivo SALVO é o recorte, não a foto crua enviada junto;
  * o recorte é aplicado mesmo sem arquivo no input (após a limpeza do input);
  * payload malformado não derruba a view (nas cópias inline antigas o
    `split(';base64,')` levantava `ValueError` -> HTTP 500).

Observação: os `save()` de Evento/Atividade/Participante re-encodam e
redimensionam a imagem gravada, então NÃO dá para comparar bytes. A prova de
que o recorte venceu usa as DIMENSÕES: o recorte tem um tamanho próprio e a
foto crua tem outro; a imagem salva precisa ter o tamanho do recorte.

O recorte é gerado com Pillow (dependência já usada pelos ImageField).
"""

import base64
import io
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .imagens import imagem_cortada
from .models import Atividade, Evento, TipoAtividade

U = get_user_model()
SENHA = "SenhaForte123!"
CPF_1 = "12345678909"
CPF_2 = "11144477735"

# Dimensões distintas de propósito: a imagem salva diz de qual das duas veio.
TAMANHO_RECORTE = (200, 200)
TAMANHO_CRU = (60, 40)


def _bytes_imagem(tamanho, cor, formato="PNG"):
    """Bytes de uma imagem real, pequena, para servir de recorte ou de foto crua."""
    buffer = io.BytesIO()
    Image.new("RGB", tamanho, cor).save(buffer, format=formato)
    return buffer.getvalue()


def _png(tamanho, cor):
    return _bytes_imagem(tamanho, cor, "PNG")


def _data_url(bytes_png):
    return "data:image/png;base64," + base64.b64encode(bytes_png).decode()


def _dimensoes(bytes_imagem):
    return Image.open(io.BytesIO(bytes_imagem)).size


class ImagemCortadaHelperTests(TestCase):
    """Contrato do helper: ausente/malformado -> None; válido -> ContentFile."""

    def setUp(self):
        self.request_factory = RequestFactory()

    def _request(self, **post):
        return self.request_factory.post("/", post)

    def test_ausente_devolve_none(self):
        self.assertIsNone(imagem_cortada(self._request(), "x"))

    def test_malformado_devolve_none(self):
        self.assertIsNone(
            imagem_cortada(self._request(cropped_image="sem-o-separador"), "x")
        )

    def _arquivo(self, corpo_base64, prefixo="atividade"):
        return imagem_cortada(self._request(cropped_image=corpo_base64), prefixo)

    def test_png_valido_devolve_contentfile(self):
        arquivo = self._arquivo(_data_url(_png((12, 12), "green")))
        assert arquivo is not None
        self.assertTrue(arquivo.name.startswith("atividade_"))
        self.assertTrue(arquivo.name.endswith(".png"))
        self.assertEqual(_dimensoes(arquivo.read()), (12, 12))

    def test_jpeg_vira_extensao_jpg(self):
        arquivo = self._arquivo(
            _data_url(_bytes_imagem((12, 12), "red", "JPEG"))
        )
        assert arquivo is not None
        self.assertTrue(arquivo.name.endswith(".jpg"))

    def test_webp_e_aceito(self):
        arquivo = self._arquivo(
            _data_url(_bytes_imagem((12, 12), "blue", "WEBP"))
        )
        assert arquivo is not None
        self.assertTrue(arquivo.name.endswith(".webp"))

    def test_extensao_vem_do_conteudo_e_nao_da_mime(self):
        # Data URL diz PNG, mas os bytes são JPEG: a whitelist confia no Pillow.
        arquivo = self._arquivo(
            _data_url(_bytes_imagem((12, 12), "black", "JPEG"))
        )
        assert arquivo is not None
        self.assertTrue(arquivo.name.endswith(".jpg"))

    def test_conteudo_que_nao_e_imagem_devolve_none(self):
        lixo = base64.b64encode(b"isto-nao-e-imagem").decode()
        self.assertIsNone(self._arquivo("data:image/png;base64," + lixo))


class _BaseCropperTests(TestCase):
    """Mídia em diretório temporário e um organizador logado com um evento."""

    def setUp(self):
        self.media = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)

        self.recorte = _png(TAMANHO_RECORTE, "red")
        self.cru = _png(TAMANHO_CRU, "blue")

        self.org = U.objects.create_user(
            email="org_cropper@example.com", password=SENHA, cpf=CPF_1,
            is_organizador=True,
        )
        self.client.force_login(self.org)

        self.evento = Evento.objects.create(
            title="Evento", description="d", local="l",
            data_inicio=datetime(2026, 10, 1).date(),
            data_fim=datetime(2026, 10, 2).date(),
            categoria="formacao", organizador=self.org,
        )

    def _enviar(self, url_name, dados, kwargs=None, campo_arquivo=None,
                arquivo_bytes=None):
        dados = dict(dados)
        if campo_arquivo and arquivo_bytes:
            dados[campo_arquivo] = SimpleUploadedFile(
                "cru.png", arquivo_bytes, content_type="image/png"
            )
        return self.client.post(reverse(url_name, kwargs=kwargs or {}), dados)


class CriarEventoRecorteTests(_BaseCropperTests):
    def _dados(self):
        return {
            "title": "Novo evento", "description": "d", "local": "l",
            "data_inicio": "2026-11-01", "data_fim": "2026-11-02",
            "categoria": "formacao",
        }

    def test_salva_o_recorte_e_nao_a_foto_crua(self):
        resposta = self._enviar(
            "organizador:criar_evento",
            {**self._dados(), "cropped_image": _data_url(self.recorte)},
            campo_arquivo="imagem", arquivo_bytes=self.cru,
        )
        self.assertEqual(resposta.status_code, 200)
        evento = Evento.objects.get(title="Novo evento")
        self.assertEqual(_dimensoes(evento.imagem.read()), TAMANHO_RECORTE)


class EditarEventoRecorteTests(_BaseCropperTests):
    def _dados(self):
        return {
            "title": "Evento editado", "description": "d", "local": "l",
            "data_inicio": "2026-10-01", "data_fim": "2026-10-02",
            "categoria": "formacao",
        }

    def test_recorte_tem_prioridade_sobre_a_foto_crua(self):
        self._enviar(
            "organizador:editar_evento",
            {**self._dados(), "cropped_image": _data_url(self.recorte)},
            kwargs={"evento_id": self.evento.id},
            campo_arquivo="imagem", arquivo_bytes=self.cru,
        )
        self.evento.refresh_from_db()
        self.assertEqual(_dimensoes(self.evento.imagem.read()), TAMANHO_RECORTE)

    def test_recorte_sozinho_sem_arquivo_ainda_e_aplicado(self):
        # Com o input de arquivo limpo, o recorte é a única fonte.
        self._enviar(
            "organizador:editar_evento",
            {**self._dados(), "cropped_image": _data_url(self.recorte)},
            kwargs={"evento_id": self.evento.id},
        )
        self.evento.refresh_from_db()
        self.assertEqual(_dimensoes(self.evento.imagem.read()), TAMANHO_RECORTE)

    def test_sem_recorte_e_sem_arquivo_mantem_a_imagem(self):
        self.evento.imagem = SimpleUploadedFile(
            "antiga.png", _png((80, 50), "black"), content_type="image/png"
        )
        self.evento.save()
        antes = _dimensoes(self.evento.imagem.read())

        self._enviar(
            "organizador:editar_evento", self._dados(),
            kwargs={"evento_id": self.evento.id},
        )
        self.evento.refresh_from_db()
        self.assertEqual(_dimensoes(self.evento.imagem.read()), antes)


class CriarEditarAtividadeRecorteTests(_BaseCropperTests):
    def setUp(self):
        super().setUp()
        self.tipo = TipoAtividade.objects.create(nome="Palestra")
        self.palestrante = U.objects.create_user(
            email="pal_cropper@example.com", password=SENHA, cpf=CPF_2,
            is_palestrante=True,
        )
        self.atividade = Atividade.objects.create(
            evento=self.evento, titulo="Abertura", descricao="d", tipo=self.tipo,
            data_hora_inicio=datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc),
            data_hora_fim=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
            n_vagas=50,
        )
        self.atividade.palestrantes.add(self.palestrante)

    def _dados(self):
        return {
            "titulo": "Abertura editada", "descricao": "d",
            "tipo": self.tipo.id, "palestrantes": [self.palestrante.id],
            "data_hora_inicio": "2026-10-01T08:00",
            "data_hora_fim": "2026-10-01T09:00",
            "n_vagas": 50,
        }

    def test_recorte_tem_prioridade_sobre_a_foto_crua(self):
        self._enviar(
            "organizador:criar_editar_atividade_editar",
            {**self._dados(), "cropped_image": _data_url(self.recorte)},
            kwargs={"evento_id": self.evento.id, "atividade_id": self.atividade.id},
            campo_arquivo="imagem", arquivo_bytes=self.cru,
        )
        self.atividade.refresh_from_db()
        # A Atividade reduz no máximo a 600x400; 200x200 passa intacto.
        self.assertEqual(_dimensoes(self.atividade.imagem.read()), TAMANHO_RECORTE)


class ProfilePaginaRecorteTests(_BaseCropperTests):
    def _dados(self):
        return {
            "first_name": "Org", "last_name": "Teste",
            "username": self.org.username, "email": self.org.email,
            "cpf": CPF_1, "telefone": "", "endereco": "",
        }

    def test_recorte_tem_prioridade_sobre_a_foto_crua(self):
        self._enviar(
            "organizador:profile",
            {**self._dados(), "cropped_image": _data_url(self.recorte)},
            campo_arquivo="foto", arquivo_bytes=self.cru,
        )
        self.org.refresh_from_db()
        # O Participante reduz no máximo a 300x300; 200x200 passa intacto.
        self.assertEqual(_dimensoes(self.org.foto.read()), TAMANHO_RECORTE)


class RecorteMalformadoTests(_BaseCropperTests):
    """Payload inválido não pode dar 500 (era o bug das cópias inline)."""

    def _dados_evento(self):
        return {
            "title": "Evento", "description": "d", "local": "l",
            "data_inicio": "2026-10-01", "data_fim": "2026-10-02",
            "categoria": "formacao",
        }

    def test_editar_evento_com_recorte_invalido_nao_derruba(self):
        resposta = self._enviar(
            "organizador:editar_evento",
            {**self._dados_evento(), "cropped_image": "lixo-sem-base64"},
            kwargs={"evento_id": self.evento.id},
            campo_arquivo="imagem", arquivo_bytes=self.cru,
        )
        self.assertNotEqual(resposta.status_code, 500)

    def test_profile_com_recorte_invalido_nao_derruba(self):
        resposta = self._enviar(
            "organizador:profile",
            {
                "first_name": "Org", "last_name": "Teste",
                "username": self.org.username, "email": self.org.email,
                "cpf": CPF_1, "telefone": "", "endereco": "",
                "cropped_image": "lixo-sem-base64",
            },
            campo_arquivo="foto", arquivo_bytes=self.cru,
        )
        self.assertNotEqual(resposta.status_code, 500)
