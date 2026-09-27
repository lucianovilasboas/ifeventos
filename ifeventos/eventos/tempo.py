"""Formatação de data/hora no FUSO LOCAL (fonte única).

Motivo: com `USE_TZ=True`, os `DateTimeField` do banco são *aware* em UTC. Se um
código formata com `.strftime()` direto, a hora sai em UTC (3h adiantada em
America/Sao_Paulo) — foi o que aconteceu com a mensagem da janela de presença do
QR do cartaz (mostrava 10:50 onde o cartaz dizia 07:50). Usar `local_legivel()`
nos pontos que formatam hora evita repetir o erro.

Uso:
    from .tempo import local_legivel
    local_legivel(atividade.data_hora_inicio)               # 10/10/2026 08:00
    local_legivel(abre_em, "%d/%m às %H:%M")                # 10/10 às 07:50
"""

from datetime import datetime

from django.utils import timezone


def local_legivel(valor, formato="%d/%m/%Y %H:%M"):
    """Formata um datetime no fuso local. Devolve "" quando não há valor.

    - Aceita `datetime` ou texto ISO (um objeto montado à mão pode chegar como
      string, como já acontece no crachá).
    - Torna *aware* o que vier sem fuso, usando o fuso corrente do Django.
    - Nunca levanta: valor inválido devolve "".
    """
    if not valor:
        return ""
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return ""
    if timezone.is_naive(valor):
        valor = timezone.make_aware(valor, timezone.get_current_timezone())
    return timezone.localtime(valor).strftime(formato)
