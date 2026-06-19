"""Project path helpers shared by scripts after file reorganization."""
from __future__ import annotations

from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    """Find the repository/project root from a file path or current directory."""
    cur = (start or Path(__file__)).resolve()
    for parent in (cur, *cur.parents):
        if (parent / "README.md").exists() and (parent / "models").exists():
            return parent
    return Path.cwd()


PROJECT_ROOT = find_project_root()
DATA_DIR = PROJECT_ROOT / "data"
MODELS_DIR = PROJECT_ROOT / "models"
CHECKPOINT_DIR = MODELS_DIR / "checkpoints"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
FIGURES_DIR = OUTPUTS_DIR / "figures"
EVALUATION_DIR = OUTPUTS_DIR / "evaluation"
LOGS_DIR = OUTPUTS_DIR / "logs"
