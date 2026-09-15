"""Importação de metadados do participante por CSV (atualiza pelo e-mail).

Reusa as regras de `eventos/metadados.py` (visibilidade, dependência e
obrigatório) — o mesmo contrato do formulário. Regras:

  - a coluna-chave é `email`; a pessoa precisa existir (e-mail inexistente é
    erro da linha);
  - o CSV é um MERGE: células vazias mantêm o valor atual; só o que vem
    preenchido sobrepõe;
  - campo que não se aplica ao vínculo da pessoa é ignorado; se o CSV tentou
    preenchê-lo, isso vira um AVISO na linha;
  - o resultado é validado de novo (obrigatório só quando visível, opções e
    dependência válidas) antes de gravar.
"""

import csv
import io
import re

from eventos import metadados

CABECALHO_EMAIL = "email"
_NUMERO = re.compile(r"^\d+([.,]\d+)?$")


def cabecalhos():
    """Cabeçalhos do CSV-modelo: `email` + as chaves configuradas."""
    return [CABECALHO_EMAIL] + [c["chave"] for c in metadados.campos()]


def _separador(primeira_linha):
    """Escolhe o delimitador pela 1ª linha (`,` `;` ou tab); padrão vírgula."""
    contagem = {d: primeira_linha.count(d) for d in (",", ";", "\t")}
    melhor = max(contagem, key=contagem.get)
    return melhor if contagem[melhor] > 0 else ","


def ler_linhas(arquivo):
    """Lê o CSV (utf-8-sig; delimitador , ; ou tab) e devolve (cabeçalho, linhas)."""
    conteudo = arquivo.read()
    if isinstance(conteudo, bytes):
        texto = conteudo.decode("utf-8-sig", errors="replace")
    else:
        texto = conteudo.lstrip("\ufeff")

    primeira = texto.splitlines()[0] if texto.splitlines() else ""
    leitor = csv.DictReader(io.StringIO(texto), delimiter=_separador(primeira))
    cabecalho = [(h or "").strip().lower() for h in (leitor.fieldnames or [])]
    linhas = [
        {(k or "").strip().lower(): (v or "").strip() for k, v in bruta.items()}
        for bruta in leitor
    ]
    return cabecalho, linhas


def _validar(valores):
    """Valida o resultado (já com a visibilidade aplicada) e devolve os erros."""
    erros = []
    for campo in metadados.campos():
        if not metadados.visivel(campo, valores):
            continue
        valor = valores.get(campo["chave"], "")
        if campo["obrigatorio"] and not valor:
            erros.append(f"'{campo['rotulo']}' é obrigatório.")
            continue
        if not valor:
            continue
        if campo["tipo"] == "escolha":
            pai = valores.get(campo["depende_de"]) if campo["depende_de"] else None
            if valor not in metadados.opcoes_do_campo(campo, pai):
                erros.append(f"'{campo['rotulo']}': '{valor}' não é um valor válido.")
        elif campo["tipo"] == "numero" and not _NUMERO.match(valor):
            erros.append(f"'{campo['rotulo']}': '{valor}' não é um número.")
    return erros


def importar(arquivo):
    """Processa o CSV e devolve o relatório por linha."""
    from eventos.models import Participante

    cabecalho, linhas = ler_linhas(arquivo)
    if CABECALHO_EMAIL not in cabecalho:
        return {
            "erro_geral": "O CSV precisa ter a coluna 'email'.",
            "total": 0, "atualizados": 0, "erros": 0, "linhas": [],
        }

    chaves = [c["chave"] for c in metadados.campos()]
    relatorio = {"total": len(linhas), "atualizados": 0, "erros": 0, "linhas": []}

    for indice, linha in enumerate(linhas, start=1):
        email = (linha.get(CABECALHO_EMAIL) or "").strip()
        item = {"indice": indice, "email": email, "status": None,
                "erros": [], "avisos": []}

        def terminar(status):
            item["status"] = status
            if status == "erro":
                relatorio["erros"] += 1
            else:
                relatorio["atualizados"] += 1
            relatorio["linhas"].append(item)

        if not email:
            item["erros"].append("linha sem e-mail.")
            terminar("erro")
            continue

        participante = Participante.objects.filter(email__iexact=email).first()
        if participante is None:
            item["erros"].append("e-mail não encontrado.")
            terminar("erro")
            continue

        # Merge: só o que veio preenchido sobrepõe o que já existe.
        base = {c: v for c, v in metadados.dados_de(participante).items() if c in chaves}
        for chave in chaves:
            valor = (linha.get(chave) or "").strip()
            if valor:
                base[chave] = valor

        # Visibilidade: campos que não se aplicam saem do resultado.
        for campo in metadados.campos():
            if metadados.visivel(campo, base):
                continue
            if (linha.get(campo["chave"]) or "").strip():
                item["avisos"].append(
                    f"'{campo['rotulo']}' ignorado (não se aplica ao vínculo)."
                )
            base.pop(campo["chave"], None)

        erros = _validar(base)
        if erros:
            item["erros"] = erros
            terminar("erro")
        else:
            metadados.salvar(participante, base)
            terminar("atualizado")

    return relatorio
