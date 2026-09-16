"""Pré-carga de alunos (planilha) e completamento do perfil no 1º acesso.

A planilha da escola (aba "Registros") é importada uma vez para `AlunoRoster`,
com a chave sendo o e-mail PESSOAL do aluno. Quando a pessoa cria a conta pelo
Google ou pelo cadastro local, `completar_do_roster` preenche os metadados de
aluno e o CPF que ela ainda não informou. Roda UMA vez, na criação da conta
(signal `user_signed_up`) — nunca sobrescreve depois.

Regras (decididas com a escola):
  - chave = e-mail pessoal; "Email Acadêmico" é ignorado (330 são "-" e parte
    aponta para e-mail de terceiros);
  - o código da turma (ex.: "I1PNIINFO1") traz o ano (I1/I2/I3), o curso
    (PNIINFO/PNIADMI/PNTGER) e o número da turma (último dígito);
  - PNEDOCIN fica de fora: não existe opção de curso equivalente;
  - campos sem lugar no sistema (sexo, turno, situação) são ignorados;
  - e-mail fora da planilha, ou conta que já existia, => nada acontece.
"""

import logging
import re
import unicodedata

from django.utils import timezone

from . import metadados
from .models import AlunoRoster
from .validators import cpf_e_valido

logger = logging.getLogger(__name__)

# Código do curso na planilha -> opção de `curso` no sistema.
MAPA_CURSO = {
    "PNIINFO": "Informática",
    "PNIADMI": "Administração",
    "PNTGER": "TPG",
}

# I1/I2/I3 -> rótulo de `ano` do sistema (só Informática/Administração).
MAPA_ANO = {"1": "Primeiro ano", "2": "Segundo ano", "3": "Terceiro ano"}

# Cabeçalhos da planilha, já normalizados (minúsculas, sem acento, um espaço).
COL_EMAIL = "email pessoal"
COL_NOME = "nome"
COL_CPF = "cpf"
COL_MATRICULA = "matricula"
COL_CURSO = "codigo curso"
COL_TURMA = "turma"

# "I1PNIINFO1" = I + ano + código do curso + número da turma (1 ou 2).
CODIGO_TURMA = re.compile(r"^I([123])(PNIINFO|PNIADMI|PNTGER)([12])$", re.IGNORECASE)


def _chave(texto):
    """Nome de coluna/chave normalizado: minúsculas, sem acento, sem pontas."""
    base = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in base if unicodedata.category(c) != "Mn").strip()


def _texto(valor):
    """Valor de célula como texto. Números inteiros do Excel perdem o `.0`."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def decodificar_turma(codigo):
    """De "I1PNIINFO1" extrai `{"ano": "Primeiro ano", "turma": "Turma 1"}`.

    Devolve `{}` quando o código não é reconhecido (ex.: "-" nos cursos TPG) —
    nesse caso ano e turma ficam de fora (são opcionais).
    """
    casamento = CODIGO_TURMA.match((codigo or "").strip())
    if not casamento:
        return {}
    ano, _curso, numero = casamento.groups()
    return {"ano": MAPA_ANO[ano], "turma": f"Turma {numero}"}


def _campo(chave):
    """Definição de um campo de metadados (ou None)."""
    return next((c for c in metadados.campos() if c["chave"] == chave), None)


def montar_dados(linha):
    """Monta os metadados de aluno a partir de uma linha normalizada.

    Devolve `{}` quando o curso não tem opção no sistema (PNEDOCIN) ou o código
    é desconhecido — a linha, então, não entra no roster.
    """
    curso = MAPA_CURSO.get(_texto(linha.get(COL_CURSO)).strip().upper())
    if not curso:
        return {}
    dados = {
        "vinculo": "Aluno",
        "matricula": _texto(linha.get(COL_MATRICULA)),
        "curso": curso,
    }
    extra = decodificar_turma(_texto(linha.get(COL_TURMA)))
    if extra:
        # `ano` só entra se for opção do curso (TPG usa "período", não "ano").
        campo_ano = _campo("ano")
        if campo_ano and extra.get("ano") in metadados.opcoes_do_campo(campo_ano, curso):
            dados["ano"] = extra["ano"]
        campo_turma = _campo("turma")
        if (campo_turma and extra.get("turma")
                and extra["turma"] in metadados.opcoes_do_campo(campo_turma)):
            dados["turma"] = extra["turma"]
    return dados


def importar_linhas(linhas):
    """Núcleo: lista de linhas (dict) -> relatório por linha.

    Separado da leitura do `.xls` para poder ser testado (e usado por outros
    formatos) sem depender do `xlrd`.
    """
    relatorio = {"total": len(linhas or []), "importados": 0, "atualizados": 0,
                 "ignorados": 0, "erros": 0, "linhas": []}

    for indice, bruta in enumerate(linhas or [], start=1):
        linha = {_chave(k): v for k, v in (bruta or {}).items()}
        email = _texto(linha.get(COL_EMAIL)).lower()
        item = {"indice": indice, "email": email, "status": None, "motivo": ""}

        def terminar(status, motivo=""):
            item["status"] = status
            item["motivo"] = motivo
            relatorio[status] = relatorio.get(status, 0) + 1
            relatorio["linhas"].append(item)

        if not email:
            terminar("erros", "linha sem e-mail.")
            continue

        dados = montar_dados(linha)
        if not dados:
            terminar("ignorados", "curso sem opção no sistema (ou código desconhecido).")
            continue

        cpf = _texto(linha.get(COL_CPF))
        if cpf and not cpf_e_valido(cpf):
            terminar("ignorados", "CPF inválido.")
            continue

        _obj, criado = AlunoRoster.objects.update_or_create(
            email=email,
            defaults={
                "nome": _texto(linha.get(COL_NOME)),
                "cpf": cpf,
                "dados": dados,
            },
        )
        terminar("importados" if criado else "atualizados")

    return relatorio


def ler_xls(caminho):
    """Lê a aba "Registros" do `.xls` e devolve a lista de linhas (dict)."""
    import xlrd

    livro = xlrd.open_workbook(caminho)
    aba = (
        livro.sheet_by_name("Registros")
        if "Registros" in livro.sheet_names()
        else livro.sheet_by_index(0)
    )
    cabecalho = aba.row_values(0)
    linhas = []
    for r in range(1, aba.nrows):
        valores = aba.row_values(r)
        linhas.append(
            {_chave(cabecalho[i]): valores[i] for i in range(len(cabecalho))
             if i < len(valores)}
        )
    return linhas


def importar_xls(caminho):
    """Importa o `.xls` para `AlunoRoster` (idempotente por e-mail)."""
    return importar_linhas(ler_xls(caminho))


def dividir_nome(nome):
    """Divide um nome completo em ``(primeiro, sobrenome)``.

    "Maria da Silva" -> ("Maria", "da Silva"); "Madonna" -> ("Madonna", "").
    Cada parte é truncada em 150 (limite do model `Participante`).
    """
    partes = (nome or "").split()
    if not partes:
        return "", ""
    return partes[0][:150], " ".join(partes[1:])[:150]


def _conferem(linha, dados, cpf):
    """O que a pessoa salvou bate com a planilha? (metadados + CPF; nome fora).

    O nome fica de fora de propósito: no Google ele vem do Google, não da
    planilha, então comparar daria divergência que não é erro.
    """
    for campo in metadados.campos():
        chave = campo["chave"]
        atual = str((dados or {}).get(chave, "") or "").strip()
        planilha = str((linha.dados or {}).get(chave, "") or "").strip()
        if atual != planilha:
            return False
    return (cpf or "") == (linha.cpf or "")


def completar_do_roster(participante):
    """Preenche metadados/CPF/nome do participante a partir do `AlunoRoster`.

    Roda só na criação da conta (ver `signals.py`). Não faz nada se o e-mail
    não estiver na planilha. O que a própria pessoa já informou tem prioridade.
    Marca a linha como usada e se o que a pessoa salvou confere com a planilha.
    Nunca levanta exceção — o login não pode quebrar por causa disto.
    """
    try:
        if participante is None or not getattr(participante, "pk", None):
            return False
        email = (participante.email or "").strip().lower()
        if not email:
            return False

        linha = AlunoRoster.objects.filter(email=email).first()
        if linha is None:
            return False

        atual = metadados.dados_de(participante)
        base = dict(linha.dados or {})
        base.update(atual)  # o que a pessoa já informou manda

        dados, erros = metadados.limpar(base)
        if erros:
            logger.warning(
                "roster: metadados invalidos para %s: %s", email, erros
            )
            return False

        metadados.salvar(participante, dados)

        campos = []
        if linha.cpf and not participante.cpf:
            participante.cpf = linha.cpf
            campos.append("cpf")
        primeiro, sobrenome = dividir_nome(linha.nome)
        if primeiro and not participante.first_name:
            participante.first_name = primeiro
            campos.append("first_name")
        if sobrenome and not participante.last_name:
            participante.last_name = sobrenome
            campos.append("last_name")
        if campos:
            participante.save(update_fields=campos)

        # Rastreio do uso: quando foi usada, se confere e o que a pessoa salvou.
        linha.usado_em = timezone.now()
        linha.confere = _conferem(linha, dados, participante.cpf)
        linha.dados_usuario = {
            "nome": f"{participante.first_name} {participante.last_name}".strip(),
            "cpf": participante.cpf,
            "metadados": dados,
        }
        linha.save(update_fields=["usado_em", "confere", "dados_usuario"])
        return True
    except Exception:
        logger.exception("roster: falha ao completar perfil de %r", getattr(participante, "email", None))
        return False
