"""Загрузка системного промпта из md-файла."""
from pathlib import Path

PROMPT_FILE = Path(__file__).resolve().parent.parent / "ПРОМПТ-агент-Abramenko-Studio.md"

def load_system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")
