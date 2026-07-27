from __future__ import annotations

from pathlib import Path

from .models import ValidationError


EXECUTABLE_NAME = "llama-server.exe"


def resolve_llama_server(folder: str | Path) -> Path:
    base = Path(folder)
    if not base.is_dir():
        raise ValidationError(f"llama.cpp folder does not exist: {base}")
    executable = base / EXECUTABLE_NAME
    if not executable.is_file():
        raise ValidationError(f'Expected "{EXECUTABLE_NAME}" directly in: {base}')
    return executable.resolve()


def discover_models(folder: str | Path) -> list[Path]:
    base = Path(folder)
    if not base.is_dir():
        raise ValidationError(f"Model folder does not exist: {base}")
    return sorted(
        (path.resolve() for path in base.iterdir() if path.is_file() and path.suffix.casefold() == ".gguf"),
        key=lambda path: (path.name.casefold(), path.name),
    )
