from __future__ import annotations

import json
from pathlib import Path

import pytest

from llamacpp_launcher.models import (
    AppSettings,
    FlashAttention,
    GpuMode,
    Profile,
    ValidationError,
)
from llamacpp_launcher.storage import SettingsStore


def make_profile(model: Path, name: str = "Default") -> Profile:
    return Profile(
        name=name,
        model_path=str(model),
        port=8080,
        ngl=35,
        context_size=8192,
        parallel_slots=2,
        flash_attention=FlashAttention.ON,
        no_mmap=True,
        gpu_mode=GpuMode.AUTO,
        custom_args='--threads 8 --alias "Pink Model"',
    )


def test_round_trip_preserves_all_fields(tmp_path: Path) -> None:
    model = tmp_path / "pink model.gguf"
    model.touch()
    path = tmp_path / "settings.json"
    settings = AppSettings(
        llama_cpp_folder=str(tmp_path),
        model_folder=str(tmp_path),
        selected_profile="Default",
        profiles=[make_profile(model)],
    )

    store = SettingsStore(path)
    store.save(settings)
    loaded = store.load()

    assert loaded.to_dict() == settings.to_dict()
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2


def test_duplicate_profile_names_are_case_insensitive(tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    model.touch()
    settings = AppSettings(
        model_folder=str(tmp_path),
        profiles=[make_profile(model, "Pink"), make_profile(model, "PINK")],
    )

    with pytest.raises(ValidationError, match="Duplicate"):
        settings.validate()


def test_malformed_file_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    store = SettingsStore(path)

    with pytest.raises(ValidationError, match="Could not load"):
        store.load()

    assert path.read_text(encoding="utf-8") == "{broken"


def test_failed_atomic_replace_preserves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"old": true}\n', encoding="utf-8")
    model = tmp_path / "model.gguf"
    model.touch()
    store = SettingsStore(path)
    settings = AppSettings(model_folder=str(tmp_path), profiles=[make_profile(model)])

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("locked")

    monkeypatch.setattr("llamacpp_launcher.storage.os.replace", fail_replace)

    with pytest.raises(ValidationError, match="locked"):
        store.save(settings)

    assert path.read_text(encoding="utf-8") == '{"old": true}\n'
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("port", [0, 65536])
def test_invalid_port(port: int, tmp_path: Path) -> None:
    model = tmp_path / "model.gguf"
    model.touch()
    profile = make_profile(model)
    profile.port = port

    with pytest.raises(ValidationError, match="Port"):
        profile.validate(str(tmp_path))
