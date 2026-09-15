"""Testes dos metadados configuráveis do participante."""

from django.http import QueryDict
from django.test import TestCase, override_settings

from eventos import metadados

CONFIG = [
    {"chave": "matricula", "rotulo": "Matrícula", "tipo": "texto", "obrigatorio": True, "ordem": 1},
    {"chave": "turma", "rotulo": "Turma", "tipo": "escolha", "opcoes": ["A", "B"], "ordem": 2},
]


class CamposMetadadosTests(TestCase):
    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_campos_normalizados_e_ordenados(self):
        campos = metadados.campos()
        self.assertEqual([c["chave"] for c in campos], ["matricula", "turma"])
        self.assertTrue(campos[0]["obrigatorio"])
        self.assertEqual(campos[1]["tipo"], "escolha")
        self.assertEqual(campos[1]["opcoes"], ["A", "B"])

    @override_settings(METADADOS_PARTICIPANTE=[])
    def test_config_vazia(self):
        self.assertEqual(metadados.campos(), [])

    @override_settings(METADADOS_PARTICIPANTE=[{"chave": "", "rotulo": "x"}])
    def test_item_sem_chave_e_ignorado(self):
        self.assertEqual(metadados.campos(), [])

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_field_de_escolha_tem_choices(self):
        campo = metadados.construir_field(metadados.campos()[1])
        self.assertEqual(campo.choices, [("", "Selecione…"), ("A", "A"), ("B", "B")])

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_colunas_selecionadas(self):
        todas = metadados.colunas_selecionadas(QueryDict(""))
        self.assertEqual([c["chave"] for c in todas], ["matricula", "turma"])

        uma = metadados.colunas_selecionadas(QueryDict("campos=matricula"))
        self.assertEqual([c["chave"] for c in uma], ["matricula"])

        nenhuma = metadados.colunas_selecionadas(QueryDict("campos="))
        self.assertEqual(nenhuma, [])

    @override_settings(METADADOS_PARTICIPANTE=CONFIG)
    def test_coletar_so_chaves_configuradas(self):
        coletado = metadados.coletar(
            {"meta_matricula": "1", "meta_turma": "B", "meta_lixo": "x"}
        )
        self.assertEqual(coletado, {"matricula": "1", "turma": "B"})
