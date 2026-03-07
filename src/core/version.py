"""Single source of truth for the package version."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("csm-dashboard")
except PackageNotFoundError:
    __version__ = "dev"
