"""pgschemadiff — PostgreSQL schema diff and migration toolkit."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pgschemadiff")
except PackageNotFoundError:
    __version__ = "0+unknown"
