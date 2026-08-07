"""Repository paths shared by the command-line entry points."""

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent
DEFAULT_VALUE_KIND_PATH = REPO_ROOT / "config" / "macro-value-kind.yml"
