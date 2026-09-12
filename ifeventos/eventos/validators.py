"""Validadores de documentos — IF Eventos.

Centraliza a normalização/validação de CPF num único lugar, para que todas as
portas de entrada (cadastro web, API, formulários do organizador) usem a mesma
regra: **guarda-se só os 11 dígitos**; a máscara é aplicada apenas na exibição.
"""

import re

from django.core.exceptions import ValidationError

# Máscara canônica de exibição: 000.000.000-00
MASCARA_CPF = "{}.{}.{}-{}"


def apenas_digitos(valor) -> str:
    """Remove tudo que não for dígito (aceita None)."""
    return re.sub(r"\D", "", valor or "")


def formatar_cpf(valor) -> str:
    """Devolve o CPF no formato 000.000.000-00 (para exibição)."""
    cpf = apenas_digitos(valor)
    if len(cpf) != 11:
        return cpf
    return MASCARA_CPF.format(cpf[:3], cpf[3:6], cpf[6:9], cpf[9:])


def _digito_verificador(parcial: str) -> int:
    """Calcula o dígito verificador de um CPF parcial (9 ou 10 dígitos)."""
    pesos = range(len(parcial) + 1, 1, -1)
    soma = sum(int(d) * p for d, p in zip(parcial, pesos))
    resto = (soma * 10) % 11
    return 0 if resto == 10 else resto


def validar_cpf(valor):
    """Valida um CPF (com ou sem máscara) e devolve os 11 dígitos.

    Levanta ``ValidationError`` quando o CPF é inválido.
    """
    cpf = apenas_digitos(valor)

    if not cpf:
        raise ValidationError("Informe o CPF.")
    if len(cpf) != 11:
        raise ValidationError("O CPF deve ter 11 dígitos.")
    if cpf == cpf[0] * 11:
        # 00000000000, 11111111111, ... são recusados pela Receita.
        raise ValidationError("CPF inválido.")

    if cpf[9] != str(_digito_verificador(cpf[:9])) or cpf[10] != str(
        _digito_verificador(cpf[:10])
    ):
        raise ValidationError("CPF inválido.")

    return cpf


def cpf_e_valido(valor) -> bool:
    """Versão booleana, para checagens rápidas (não levanta exceção)."""
    try:
        validar_cpf(valor)
    except ValidationError:
        return False
    return True
