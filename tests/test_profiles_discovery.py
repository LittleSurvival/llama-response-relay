from __future__ import annotations

from pathlib import Path

import pytest

from llamacpp_launcher.discovery import discover_models, resolve_llama_server
from llamacpp_launcher.models import AppSettings, Profile, ValidationError
from llamacpp_launcher.profiles import ProfileService


def profile(model: Path, name: str = "One") -> Profile:
    return Profile(name=name, model_path=str(model))


def test_resolve_llama_server_requires_direct_child(tmp_path: Path) -> None:
    nested = tmp_path / "bin"
    nested.mkdir()
    (nested / "llama-server.exe").touch()

    with pytest.raises(ValidationError, match="directly"):
        resolve_llama_server(tmp_path)

    direct = tmp_path / "llama-server.exe"
    direct.touch()
    assert resolve_llama_server(tmp_path) == direct.resolve()


def test_discover_models_is_non_recursive_case_insensitive_and_sorted(tmp_path: Path) -> None:
    (tmp_path / "zeta.GGUF").touch()
    (tmp_path / "Alpha.gguf").touch()
    (tmp_path / "ignore.txt").touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "hidden.gguf").touch()

    assert [item.name for item in discover_models(tmp_path)] == ["Alpha.gguf", "zeta.GGUF"]


def test_profile_crud_and_selection(tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    model.touch()
    settings = AppSettings(model_folder=str(tmp_path))
    service = ProfileService(settings)

    created = service.create(profile(model))
    duplicate = service.duplicate(created.name)
    assert service.names() == ["One", "One Copy"]
    assert settings.selected_profile == duplicate.name

    updated = profile(model, "Renamed")
    service.update(duplicate.name, updated)
    assert settings.selected_profile == "Renamed"

    service.select("One")
    service.delete("Renamed")
    assert service.names() == ["One"]
    assert service.get("one").name == "One"


def test_profile_service_rejects_duplicate_and_running_delete(tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    model.touch()
    service = ProfileService(
        AppSettings(model_folder=str(tmp_path), profiles=[profile(model, "Pink")])
    )

    with pytest.raises(ValidationError, match="already"):
        service.create(profile(model, "PINK"))
    with pytest.raises(ValidationError, match="Stop"):
        service.delete("Pink", running_profile="pink")


def test_missing_saved_model_path_is_preserved_but_invalid(tmp_path: Path) -> None:
    missing = tmp_path / "missing.gguf"
    saved = profile(missing)
    settings = AppSettings.from_dict(
        {
            "model_folder": str(tmp_path),
            "selected_profile": "One",
            "profiles": [saved.to_dict()],
        }
    )

    assert settings.profiles[0].model_path == str(missing)
    with pytest.raises(ValidationError, match="does not exist"):
        settings.profiles[0].validate(settings.model_folder, require_files=True)
