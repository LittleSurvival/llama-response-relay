from __future__ import annotations

import json
from pathlib import Path

import pytest

from llamacpp_launcher.glossaries import GlossaryService
from llamacpp_launcher.models import (
    AppSettings,
    Glossary,
    GlossaryEntry,
    Profile,
    SCHEMA_VERSION,
    ValidationError,
)
from llamacpp_launcher.storage import SettingsStore


def test_version_one_settings_migrate_in_memory_and_save_as_version_two(
    tmp_path: Path,
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "llama_cpp_folder": "C:/llama",
                "model_folder": "C:/models",
                "profiles": [],
            }
        ),
        encoding="utf-8",
    )
    store = SettingsStore(path)

    loaded = store.load()

    assert loaded.schema_version == SCHEMA_VERSION
    assert loaded.interceptor_host == "127.0.0.1"
    assert loaded.interceptor_port == 8081
    assert loaded.interceptor_enabled is True
    assert loaded.glossaries == []
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1

    store.save(loaded)
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2


def test_glossary_round_trip_and_global_selection(tmp_path: Path) -> None:
    glossary = Glossary(
        name="Names",
        entries=[
            GlossaryEntry(
                source="Alice",
                replacement="愛麗絲",
                enabled=True,
                case_sensitive=False,
            )
        ],
    )
    profile = Profile(
        name="Chat",
        model_path=str(tmp_path / "model.gguf"),
    )
    settings = AppSettings(
        profiles=[profile],
        glossaries=[glossary],
        selected_glossary_id=glossary.id,
    )
    path = tmp_path / "settings.json"

    SettingsStore(path).save(settings)
    loaded = SettingsStore(path).load()

    assert loaded.glossaries[0].to_dict() == glossary.to_dict()
    assert loaded.selected_glossary_id == glossary.id
    assert "glossary_id" not in loaded.profiles[0].to_dict()


def test_legacy_profile_glossary_id_is_ignored_on_load(tmp_path: Path) -> None:
    glossary = Glossary(name="Terms")
    settings = AppSettings.from_dict(
        {
            "schema_version": 2,
            "profiles": [
                {
                    "name": "Chat",
                    "model_path": str(tmp_path / "model.gguf"),
                    "glossary_id": glossary.id,
                }
            ],
            "glossaries": [glossary.to_dict()],
            "selected_glossary_id": glossary.id,
        }
    )

    assert "glossary_id" not in settings.profiles[0].to_dict()
    assert settings.selected_glossary_id == glossary.id


def test_glossary_service_crud_and_selected_glossary_deletion() -> None:
    settings = AppSettings()
    service = GlossaryService(settings)
    created = service.create(Glossary(name="Terms"))
    remaining = service.create(Glossary(name="Remaining"))

    renamed = service.rename(created.id, "Character names")
    assert renamed.id == created.id
    service.select(created.id)
    service.delete(created.id)
    assert settings.selected_glossary_id == remaining.id


def test_glossary_validation_rejects_names_and_duplicate_enabled_sources() -> None:
    service = GlossaryService(AppSettings())
    service.create(Glossary(name="Terms"))
    with pytest.raises(ValidationError, match="already"):
        service.create(Glossary(name="TERMS"))

    glossary = Glossary(
        name="Duplicates",
        entries=[
            GlossaryEntry(source="Llama", replacement="A", case_sensitive=False),
            GlossaryEntry(source="llama", replacement="B", case_sensitive=False),
        ],
    )
    with pytest.raises(ValidationError, match="Duplicate enabled"):
        glossary.validate()
