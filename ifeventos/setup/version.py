"""Versão do produto (fonte única).

O esquema é SemVer (`MAJOR.MINOR.PATCH`). Durante o ciclo da V2.0 a versão fica
em pré-release (`2.0.0-dev.N`) e cada onda ganha uma tag git correspondente.

O valor pode ser sobrescrito pelo ambiente (`APP_VERSION`) sem editar o código —
útil para marcar um build específico no deploy. Quem lê é
`settings.APP_VERSION` (ver `setup/settings.py`).
"""

__version__ = "2.4.0"

# Rótulo curto usado na interface (footer/admin). Mantém o "v" do padrão git.
__version_label__ = f"v{__version__}"
