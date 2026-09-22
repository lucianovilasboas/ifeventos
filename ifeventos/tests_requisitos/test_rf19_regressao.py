"""RF-19 - Nao-regressao: os 17 itens "Corrigido" do CHANGELOG.md.

Cada caso e a releitura observavel de uma correcao documentada: a expectativa vem do
proprio item (linha citada), medida no HTTP/HTML/CSS - nunca do codigo.
"""

import re

from django.contrib.staticfiles import finders
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from .base import RequisitosTestCase

PNG_1X1 = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
           b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
           b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def css_do_app(nome="css/app/main.css"):
    caminho = finders.find(nome)
    return open(caminho, encoding="utf-8").read() if caminho else ""


def bloco_css(css, seletor):
    m = re.search(re.escape(seletor) + r"\s*\{(.*?)\}", css, re.S)
    return m.group(1) if m else ""


class _Base19(RequisitosTestCase):
    def setUp(self):
        self.u = self.dono("r19-dono@req.test")
        self.e = self.evento(self.u)
        self.tp = self.tipo("Palestra R19")
        self.esp = self.espaco("Sala R19", capacidade=40)
        self.chamada_aberta(self.e)
        self.vaga(self.e, self.esp, capacidade=40)
        self.prop = self.participante("r19-prop@req.test")

    def pendente(self, **kw):
        dados = dict(titulo="Proposta R19", publicada=False, situacao="pendente",
                     tipo=self.tp, proponente=self.prop)
        dados.update(kw)
        return self.atividade(self.e, **dados)

    def html(self, rota, usuario=None):
        self.logar(usuario or self.prop)
        return self.client.get(rota).content.decode("utf-8", "ignore")


# ---------------------------------------------------------------- 2.2.6 / 2.2.5
class DefinirSenhaTests(_Base19):
    def test_T_R01_definir_senha_usa_o_layout_do_app(self):
        """CHANGELOG.md:74 (2.2.6)."""
        self.requisito("RF-19", "CHANGELOG.md:74")
        from django.contrib.auth import get_user_model
        novo = get_user_model().objects.create_user(email="r19-semsenha@req.test", password=None, cpf="")
        novo.set_unusable_password()
        novo.save()
        self.logar(novo)
        r = self.client.get("/accounts/password/set/")
        html = r.content.decode("utf-8", "ignore")
        self.assertEqual(r.status_code, 200, "a pagina de definir senha deve abrir")
        self.assertRegex(html, r"/static/[^\"]+\.css",
                         "a pagina de senha deve carregar o CSS do app (layout proprio)")
        for marca_allauth in ("Conexões", "Gerenciar e-mails", "allauth"):
            self.assertNotIn(marca_allauth, html,
                             f"menu padrao do allauth presente: {marca_allauth}")


class PerfilValidacaoTests(_Base19):
    def _campos_perfil(self, html):
        m = re.search(r"<form([^>]*action=\"/participante/dashboard/\"[^>]*)>(.*?)</form>", html, re.S)
        return m.group(2) if m else ""

    def test_T_R02_erro_de_validacao_do_perfil_aparece_na_tela(self):
        """CHANGELOG.md:87 (2.2.5)."""
        self.requisito("RF-19", "CHANGELOG.md:87")
        html = self.html("/participante/dashboard/")
        campos = self._campos_perfil(html)
        nomes = re.findall(r'name="([^"]+)"', campos)
        self.assertTrue(nomes, "nao localizei o formulario de perfil renderizado")
        dados = {n: "" for n in nomes}
        dados.update({"email": self.prop.email, "cpf": "111.111.111-11", "first_name": "Teste"})
        r = self.client.post("/participante/dashboard/", dados)
        corpo = r.content.decode("utf-8", "ignore")
        self.assertEqual(r.status_code, 200, "validacao invalida deve re-renderizar a tela")
        tem_erro = bool(re.search(r"(inv[aá]lido|obrigat[oó]rio|CPF)", corpo, re.I))
        self.assertTrue(tem_erro, "nenhuma mensagem de erro apareceu para CPF invalido")

    def test_T_R03_mensagem_de_obrigatorio_nao_se_repete_por_campo(self):
        """CHANGELOG.md:94 (2.2.5): a mesma mensagem aparecia duas vezes."""
        self.requisito("RF-19", "CHANGELOG.md:94")
        html = self.html("/participante/dashboard/")
        campos = self._campos_perfil(html)
        dados = {n: "" for n in re.findall(r'name="([^"]+)"', campos)}
        dados["email"] = self.prop.email
        r = self.client.post("/participante/dashboard/", dados)
        corpo = r.content.decode("utf-8", "ignore")
        por_campo = {}
        for m in re.finditer(r"Este campo [eé] obrigat[oó]rio", corpo, re.I):
            contexto = corpo[max(0, m.start() - 400):m.start()]
            marcadores = re.findall(r'(?:id|for)="id_([a-z_]+)"', contexto)
            if marcadores:
                por_campo[marcadores[-1]] = por_campo.get(marcadores[-1], 0) + 1
        if not por_campo:
            self.skipTest("nao consegui associar a mensagem a um campo no HTML renderizado "
                          f"(a tela usa apenas blocos text-danger: {len(re.findall('text-danger', corpo))})")
        duplicados = {k: v for k, v in por_campo.items() if v > 1}
        self.assertEqual(duplicados, {}, f"mensagem repetida no mesmo campo: {por_campo}")

    def test_T_R04_perfil_exige_vinculo_e_cpf_no_servidor(self):
        """CHANGELOG.md:97 (2.2.5): o formulario exige Vinculo (e CPF)."""
        self.requisito("RF-19", "CHANGELOG.md:97")
        html = self.html("/participante/dashboard/")
        nomes = re.findall(r'name="([^"]+)"', self._campos_perfil(html))
        dados = {n: "" for n in nomes}
        dados.update({"email": self.prop.email, "first_name": "Sem Vinculo"})
        r = self.client.post("/participante/dashboard/", dados)
        corpo = r.content.decode("utf-8", "ignore")
        faltando = [campo for campo in ("cpf", "vinculo") if campo not in corpo.lower()]
        self.assertEqual(faltando, [],
                         f"o servidor nao sinalizou os campos obrigatorios: {faltando}")


# ---------------------------------------------------------------- 2.2.4 / 2.2.3 (CSS da grade)
class GradeCssTests(_Base19):
    def test_T_R05_gutter_da_agenda_esta_na_margin_do_container(self):
        """CHANGELOG.md:106 (2.2.4) e :122 (2.2.3)."""
        self.requisito("RF-19", "CHANGELOG.md:106,122")
        bloco = bloco_css(css_do_app(), ".agenda-scroll")
        self.assertTrue(bloco, "regra .agenda-scroll nao encontrada no CSS do app")
        margens = re.findall(r"margin[^;]*;", bloco)
        paddings = re.findall(r"padding[^;]*;", bloco)
        self.assertTrue(any("--gutter-phone" in m for m in margens),
                        f"o gutter nao esta na margin: {bloco.strip()[:200]}")
        self.assertFalse(any("--gutter-phone" in p for p in paddings),
                         f"o gutter continua no padding: {bloco.strip()[:200]}")

    def test_T_R06_coluna_de_horarios_tem_largura_fixa_de_48px(self):
        """CHANGELOG.md:122 (2.2.3)."""
        self.requisito("RF-19", "CHANGELOG.md:122")
        bloco = bloco_css(css_do_app(), ".agenda .agenda-hora")
        self.assertTrue(bloco, "regra .agenda .agenda-hora nao encontrada")
        for prop in ("width", "min-width", "max-width"):
            self.assertRegex(bloco, prop + r"\s*:\s*48px",
                             f"{prop} da coluna de horarios nao e 48px: {bloco.strip()[:200]}")


# ---------------------------------------------------------------- 2.2.2 (autorizacao)
class AutorizacaoRegressaoTests(_Base19):
    def test_T_R07_rotas_de_escrita_do_organizador_recusam_participante(self):
        """CHANGELOG.md:139-142 (2.2.2)."""
        self.requisito("RF-19", "CHANGELOG.md:139-142")
        a = self.atividade(self.e, publicada=False)
        self.logar(self.prop)
        rotas = [("post", f"/organizador/atividade/{a.id}/publicar/"),
                 ("post", f"/organizador/excluir_atividade/{a.id}/"),
                 ("get", f"/organizador/criar_atividade/{self.e.id}/"),
                 ("post", f"/organizador/editar_atividade/{a.id}/")]
        permitidas = []
        for metodo, rota in rotas:
            r = getattr(self.client, metodo)(rota)
            if r.status_code < 400 and r.status_code != 302:
                permitidas.append(f"{metodo.upper()} {rota} -> {r.status_code}")
        self.assertEqual(permitidas, [], f"rotas de escrita abertas a participante: {permitidas}")
        self.assertFalse(type(a).objects.get(pk=a.id).publicada, "atividade foi publicada")

    def test_T_R08_acoes_globais_e_ia_exigem_flag_de_organizador(self):
        """CHANGELOG.md:144-149 (2.2.2)."""
        self.requisito("RF-19", "CHANGELOG.md:144,149")
        self.logar(self.prop)
        rotas = ["/organizador/metadados/modelo.csv", "/organizador/importar_metadados/",
                 "/organizador/gerar_descricao/", "/organizador/sugerir_categoria/",
                 "/organizador/ia_mensagem/"]
        abertas = {}
        for rota in rotas:
            r = self.client.get(rota)
            if r.status_code == 200:
                abertas[rota] = r.status_code
            elif r.status_code not in (302, 403, 404, 405):
                abertas[rota] = r.status_code
        self.assertEqual(abertas, {}, f"acoes globais/IA sem a flag: {abertas}")

    def test_T_R09_certificados_exigem_organizador(self):
        """CHANGELOG.md:147 (2.2.2)."""
        self.requisito("RF-19", "CHANGELOG.md:147")
        a = self.atividade(self.e)
        from eventos.models import Inscricao
        ins = Inscricao.objects.create(atividade=a, participante=self.prop, confirmada=True)
        self.logar(self.prop)
        abertas = {}
        for rota in (f"/organizador/emitir-certificado/inscricao/{ins.id}/",
                     f"/organizador/emitir-certificados/atividade/{a.id}/",
                     f"/organizador/emitir-certificados/evento/{self.e.id}/"):
            r = self.client.post(rota)
            if r.status_code not in (302, 403, 404):
                abertas[rota] = r.status_code
        self.assertEqual(abertas, {}, f"emissao de certificado acessivel a participante: {abertas}")

    def test_T_R10_equipe_de_apoio_continua_fazendo_checkin(self):
        """CHANGELOG.md:151 (2.2.2): a equipe de apoio nao e afetada."""
        self.requisito("RF-19", "CHANGELOG.md:151")
        equipe = self.usuario("r19-equipe@req.test", cpf="11144477735", is_equipe=True)
        self.e.equipe.add(equipe)
        a = self.atividade(self.e, titulo="Atividade Apoio R19")
        from eventos.models import Inscricao
        Inscricao.objects.create(atividade=a, participante=self.prop, confirmada=True)
        self.logar(equipe)
        tela = self.client.get(f"/apoio/evento/{self.e.id}/")
        self.assertEqual(tela.status_code, 200, "equipe de apoio deve abrir a tela do proprio evento")
        r = self.api("post", "/api/v1/presencas/", {"atividade": a.id, "participante": self.prop.id},
                     token=self.token(equipe))
        self.assertIn(r.status_code, (200, 201),
                      f"equipe de apoio deve conseguir registrar presenca: {r.status_code} "
                      f"{r.content[:160]}")


# ---------------------------------------------------------------- 2.1.3 / 2.1.2 (proposicoes)
class PropostasRegressaoTests(_Base19):
    def _profundidade_forms(self, html):
        prof = mx = 0
        for tok in re.finditer(r"<form[^>]*>|</form>", html, re.I):
            if tok.group(0).lower().startswith("</"):
                prof -= 1
            else:
                prof += 1
                mx = max(mx, prof)
        return mx

    def test_T_R11_tela_de_propostas_pendentes_sem_form_aninhado(self):
        """CHANGELOG.md:249 (2.1.3)."""
        self.requisito("RF-19", "CHANGELOG.md:249")
        self.pendente()
        html = self.html(f"/organizador/propostas/{self.e.id}/", usuario=self.u)
        self.assertEqual(self._profundidade_forms(html), 1,
                         "ha <form> aninhado na tela de propostas pendentes")

    def test_T_R12_recorte_da_imagem_preservado_quando_a_validacao_falha(self):
        """CHANGELOG.md:260 (2.1.2)."""
        self.requisito("RF-19", "CHANGELOG.md:260")
        self.logar(self.prop)
        recorte = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        r = self.client.post(f"/participante/propostas/{self.e.id}/nova/",
                             {"vaga": str(self.vaga(self.e, self.espaco("Sala R19b"), capacidade=5).id),
                              "titulo": "", "descricao": "", "cropped_image": recorte})
        corpo = r.content.decode("utf-8", "ignore")
        self.assertIn(recorte, corpo,
                      "o recorte da imagem foi perdido quando a validacao falhou")

    def test_T_R13_tela_de_aprovacao_mostra_a_imagem_do_proponente(self):
        """CHANGELOG.md:263-264 (2.1.2)."""
        self.requisito("RF-19", "CHANGELOG.md:263-264")
        imagem = SimpleUploadedFile("proposta-r19.png", PNG_1X1, content_type="image/png")
        a = self.pendente()
        a.imagem = imagem
        a.save()
        nome_arquivo = a.imagem.name.split("/")[-1]
        html = self.html(f"/organizador/propostas/{self.e.id}/", usuario=self.u)
        self.assertIn(nome_arquivo, html,
                      f"a imagem enviada pelo proponente nao aparece na aprovacao: {nome_arquivo}")

    def test_T_R14_botao_para_cadastrar_tipo_sugerido_pelo_proponente(self):
        """CHANGELOG.md:265 (2.1.2)."""
        self.requisito("RF-19", "CHANGELOG.md:265")
        self.pendente(tipo=None, tipo_sugerido="Oficina Fora do Catalogo")
        html = self.html(f"/organizador/propostas/{self.e.id}/", usuario=self.u)
        botoes = [re.sub(r"<[^>]+>", " ", b).strip() for b in
                  re.findall(r"<button[^>]*>.*?</button>", html, re.S | re.I)]
        oferece = bool(re.search(r"cadastrar\s+tipo|novo\s+tipo|sugerir-tipo|cadastrar-tipo", html, re.I))
        self.assertTrue(
            oferece,
            f"tipo sugerido sem caminho de cadastro na aprovacao; botoes da tela: {botoes[:12]}",
        )

    def test_T_R15_busca_de_palestrante_encontra_quem_ja_e_cadastrado(self):
        """CHANGELOG.md:268 (2.1.2): e-mail ja cadastrado vira palestrante, nao sugestao."""
        self.requisito("RF-19", "CHANGELOG.md:268")
        cadastrado = self.usuario("r19-jacadastrado@req.test", cpf="11144477735",
                                  first_name="Maria", last_name="Ja Cadastrada")
        self.logar(self.prop)
        achou = self.client.get("/participante/propostas/buscar-participante/",
                                {"q": cadastrado.email})
        self.assertEqual(achou.status_code, 200, "busca de participante deve responder 200")
        corpo = achou.content.decode("utf-8", "ignore")
        self.assertIn(cadastrado.email, corpo,
                      f"quem ja e cadastrado nao foi encontrado pela busca: {corpo[:200]}")
        inexistente = self.client.get("/participante/propostas/buscar-participante/",
                                      {"q": "ninguem-xyz@req.test"})
        self.assertNotIn("ninguem-xyz@req.test", inexistente.content.decode("utf-8", "ignore"),
                         "a busca devolveu quem nao existe")

    def test_T_R16_chips_de_palestrantes_preservados_na_edicao(self):
        """CHANGELOG.md:278 (2.1.1)."""
        self.requisito("RF-19", "CHANGELOG.md:278")
        colega = self.usuario("r19-colega@req.test", cpf="11144477735",
                              first_name="Colega", last_name="Chips Preservados")
        a = self.pendente()
        a.palestrantes.add(colega)
        html = self.html(f"/participante/propostas/{a.id}/editar/")
        self.assertIn("Chips Preservados", html,
                      "os palestrantes ja informados nao aparecem na edicao da proposta")


# ---------------------------------------------------------------- 2.1.1 (formulario de proposta)
class FormularioPropostaTests(_Base19):
    def test_T_R17_eu_vou_ministrar_vem_marcado_por_padrao(self):
        """CHANGELOG.md:281 (2.1.1)."""
        self.requisito("RF-19", "CHANGELOG.md:281")
        html = self.html(f"/participante/propostas/{self.e.id}/nova/")
        m = re.search(r"<input[^>]*name=\"eu_sou_palestrante\"[^>]*>", html)
        self.assertIsNotNone(m, "o campo 'Eu vou ministrar' nao esta no formulario")
        self.assertIn("checked", m.group(0), "o campo nao vem marcado por padrao")

    def test_T_R18_select_multiplo_de_palestrantes_removido(self):
        """CHANGELOG.md:284 (2.1.1)."""
        self.requisito("RF-19", "CHANGELOG.md:284")
        for nome in ("Ana Lista Exposta", "Bruno Lista Exposta", "Carla Lista Exposta"):
            p = self.usuario(f"r19-{nome.split()[0].lower()}@req.test", cpf="11144477735",
                             first_name=nome.split()[0], last_name="Lista Exposta", is_palestrante=True)
        html = self.html(f"/participante/propostas/{self.e.id}/nova/")
        multiplos = re.findall(r"<select[^>]*multiple[^>]*>", html, re.I)
        self.assertEqual(multiplos, [], f"select multiplo voltou ao formulario: {multiplos}")
        expostos = [n for n in ("Ana Lista Exposta", "Bruno Lista Exposta", "Carla Lista Exposta")
                    if n in html]
        self.assertEqual(expostos, [], f"lista de palestrantes exposta no formulario: {expostos}")

    def test_T_R19_campo_de_imagem_da_proposta_usa_cropper(self):
        """CHANGELOG.md:287 (2.1.1)."""
        self.requisito("RF-19", "CHANGELOG.md:287")
        html = self.html(f"/participante/propostas/{self.e.id}/nova/")
        self.assertIn("cropperjs", html.lower(), "o Cropper nao esta carregado no formulario")
        self.assertRegex(html, r'name="cropped_image"', "campo cropped_image ausente")
        self.assertRegex(html, r'name="imagem"', "campo de imagem ausente")


# ---------------------------------------------------------------- 2.0.1 (concierge)
class ConciergeTests(_Base19):
    @override_settings(IA_ATIVA=False)
    def test_T_R20_concierge_responde_o_evento_de_hoje(self):
        """CHANGELOG.md:314 (2.0.1): respondia com o primeiro evento em vez do de hoje."""
        self.requisito("RF-19", "CHANGELOG.md:314")
        from datetime import date, timedelta
        hoje = date.today()
        from datetime import datetime
        from datetime import timezone as tz
        antigo = self.evento(self.u, title="Evento Antigo R19",
                             data_inicio=hoje - timedelta(days=90),
                             data_fim=hoje - timedelta(days=88))
        atual = self.evento(self.u, title="Evento De Hoje R19",
                            data_inicio=hoje - timedelta(days=1), data_fim=hoje + timedelta(days=1))
        # a heuristica responde por ATIVIDADE publicada, entao cada evento precisa da sua
        self.atividade(antigo, titulo="Oficina Antiga R19", publicada=True,
                       data_hora_inicio=datetime.combine(hoje - timedelta(days=90),
                                                         datetime.min.time()).replace(hour=10, tzinfo=tz.utc),
                       data_hora_fim=datetime.combine(hoje - timedelta(days=90),
                                                      datetime.min.time()).replace(hour=11, tzinfo=tz.utc))
        self.atividade(atual, titulo="Oficina De Hoje R19", publicada=True,
                       data_hora_inicio=datetime.combine(hoje, datetime.min.time()).replace(hour=10, tzinfo=tz.utc),
                       data_hora_fim=datetime.combine(hoje, datetime.min.time()).replace(hour=11, tzinfo=tz.utc))
        self.logar(self.prop)
        pagina = self.client.get("/participante/assistente/").content.decode("utf-8", "ignore")
        token_csrf = (re.search(r'"X-CSRFToken":\s*"([^"]+)"', pagina)
                      or re.search(r"name=\"csrfmiddlewaretoken\" value=\"([^\"]+)\"", pagina))
        cabecalho = {"HTTP_X_CSRFTOKEN": token_csrf.group(1)} if token_csrf else {}
        respostas = {}
        for corpo in ({"mensagem": "qual é o evento de hoje?", "historico": []},
                      {"mensagem": "qual é o evento de hoje?"}):
            r = self.client.post("/participante/assistente/responder/", corpo,
                                 content_type="application/json", **cabecalho)
            respostas[str(corpo)] = (r.status_code, r.content.decode("utf-8", "ignore")[:300])
        aceitas = {k: v for k, v in respostas.items() if v[0] == 200}
        self.assertTrue(aceitas, f"o concierge nao aceitou nenhuma forma de pergunta: {respostas}")
        texto = " ".join(v[1] for v in aceitas.values())  # a resposta vem na chave 'resposta' 
        self.assertTrue(
            "Evento De Hoje R19" in texto or "Oficina De Hoje R19" in texto,
            f"o concierge nao apontou a programacao de hoje: {texto[:400]}",
        )
        self.assertNotIn("Antiga", texto,
                         f"o concierge respondeu a programacao antiga em vez da de hoje: {texto[:400]}")
