from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
import ipaddress
import re
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = 2
PROFILE_NAME_PATTERN = re.compile(r"^[^<>:\"/\\|?*\x00-\x1f]+$")


class ValidationError(ValueError):
    """A user-correctable configuration error."""


class GpuMode(StrEnum):
    AUTO = "auto"
    SINGLE = "single"
    MULTI = "multi"


class FlashAttention(StrEnum):
    AUTO = "auto"
    ON = "on"
    OFF = "off"


def new_id() -> str:
    return str(uuid4())


@dataclass(slots=True)
class GlossaryEntry:
    source: str
    replacement: str
    enabled: bool = True
    case_sensitive: bool = True
    id: str = field(default_factory=new_id)

    def validate(self) -> None:
        self.source = self.source.strip()
        if not self.id.strip():
            raise ValidationError("Glossary entry id is required.")
        if not self.source:
            raise ValidationError("Glossary source text is required.")
        if len(self.source) > 4096:
            raise ValidationError("Glossary source text is too long.")
        if len(self.replacement) > 16_384:
            raise ValidationError("Glossary replacement text is too long.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GlossaryEntry:
        try:
            entry = cls(
                id=str(data.get("id") or new_id()),
                source=str(data["source"]),
                replacement=str(data.get("replacement", "")),
                enabled=bool(data.get("enabled", True)),
                case_sensitive=bool(data.get("case_sensitive", True)),
            )
        except (KeyError, TypeError) as exc:
            raise ValidationError(f"Invalid glossary entry data: {exc}") from exc
        entry.validate()
        return entry


@dataclass(slots=True)
class Glossary:
    name: str
    entries: list[GlossaryEntry] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    def validate(self) -> None:
        self.name = self.name.strip()
        if not self.id.strip():
            raise ValidationError("Glossary id is required.")
        if not self.name:
            raise ValidationError("Glossary name is required.")
        if len(self.name) > 80 or not PROFILE_NAME_PATTERN.fullmatch(self.name):
            raise ValidationError("Glossary name contains unsupported characters or is too long.")
        entry_ids: set[str] = set()
        active_sources: set[tuple[bool, str]] = set()
        for entry in self.entries:
            entry.validate()
            if entry.id in entry_ids:
                raise ValidationError(f'Duplicate glossary entry id: "{entry.id}".')
            entry_ids.add(entry.id)
            if not entry.enabled:
                continue
            source_key = entry.source if entry.case_sensitive else entry.source.casefold()
            key = (entry.case_sensitive, source_key)
            if key in active_sources:
                raise ValidationError(
                    f'Duplicate enabled glossary source: "{entry.source}".'
                )
            active_sources.add(key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Glossary:
        try:
            glossary = cls(
                id=str(data.get("id") or new_id()),
                name=str(data["name"]),
                entries=[
                    GlossaryEntry.from_dict(item) for item in data.get("entries", [])
                ],
            )
        except (KeyError, TypeError) as exc:
            raise ValidationError(f"Invalid glossary data: {exc}") from exc
        glossary.validate()
        return glossary


@dataclass(slots=True)
class Profile:
    name: str
    model_path: str
    host: str = "127.0.0.1"
    port: int = 8080
    ngl: int = 0
    context_size: int = 4096
    parallel_slots: int = 1
    flash_attention: FlashAttention = FlashAttention.AUTO
    no_mmap: bool = False
    gpu_mode: GpuMode = GpuMode.AUTO
    custom_args: str = ""

    def validate(self, model_folder: str = "", *, require_files: bool = True) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError("Profile name is required.")
        if len(self.name) > 80 or not PROFILE_NAME_PATTERN.fullmatch(self.name):
            raise ValidationError("Profile name contains unsupported characters or is too long.")
        if not self.host.strip():
            raise ValidationError("Host is required.")
        _validate_host(self.host.strip())
        if not 1 <= int(self.port) <= 65535:
            raise ValidationError("Port must be between 1 and 65535.")
        if not 0 <= int(self.ngl) <= 999:
            raise ValidationError("-ngl must be between 0 and 999.")
        if not 1 <= int(self.context_size) <= 16_777_216:
            raise ValidationError("-c must be a positive value.")
        if not 1 <= int(self.parallel_slots) <= 1024:
            raise ValidationError("-np must be between 1 and 1024.")
        try:
            self.flash_attention = FlashAttention(self.flash_attention)
            self.gpu_mode = GpuMode(self.gpu_mode)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if not self.model_path:
            raise ValidationError("A model must be selected.")
        model = Path(self.model_path)
        if model.suffix.casefold() != ".gguf":
            raise ValidationError("The selected model must be a .gguf file.")
        if (
            require_files
            and model_folder
            and model.parent.resolve(strict=False) != Path(model_folder).resolve(strict=False)
        ):
            raise ValidationError("The selected model must be directly inside the model folder.")
        if require_files and not model.is_file():
            raise ValidationError(f"Model file does not exist: {model}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["flash_attention"] = self.flash_attention.value
        data["gpu_mode"] = self.gpu_mode.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        try:
            return cls(
                name=str(data["name"]),
                model_path=str(data["model_path"]),
                host=str(data.get("host", "127.0.0.1")),
                port=int(data.get("port", 8080)),
                ngl=int(data.get("ngl", 0)),
                context_size=int(data.get("context_size", 4096)),
                parallel_slots=int(data.get("parallel_slots", 1)),
                flash_attention=FlashAttention(data.get("flash_attention", "auto")),
                no_mmap=bool(data.get("no_mmap", False)),
                gpu_mode=GpuMode(data.get("gpu_mode", "auto")),
                custom_args=str(data.get("custom_args", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid profile data: {exc}") from exc


@dataclass(slots=True)
class AppSettings:
    schema_version: int = SCHEMA_VERSION
    llama_cpp_folder: str = ""
    model_folder: str = ""
    selected_profile: str = ""
    startup_timeout_seconds: float = 120.0
    shutdown_timeout_seconds: float = 10.0
    profiles: list[Profile] = field(default_factory=list)
    interceptor_enabled: bool = True
    interceptor_host: str = "127.0.0.1"
    interceptor_port: int = 8081
    selected_glossary_id: str = ""
    glossaries: list[Glossary] = field(default_factory=list)

    def validate(self, *, require_files: bool = False) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValidationError(
                f"Unsupported settings schema {self.schema_version}; expected {SCHEMA_VERSION}."
            )
        if self.startup_timeout_seconds <= 0:
            raise ValidationError("Startup timeout must be positive.")
        if self.shutdown_timeout_seconds <= 0:
            raise ValidationError("Shutdown timeout must be positive.")
        _validate_host(self.interceptor_host.strip())
        if not 1 <= int(self.interceptor_port) <= 65535:
            raise ValidationError("LRR port must be between 1 and 65535.")
        names: set[str] = set()
        for profile in self.profiles:
            profile.validate(self.model_folder, require_files=require_files)
            key = profile.name.casefold()
            if key in names:
                raise ValidationError(f'Duplicate profile name: "{profile.name}".')
            names.add(key)
        if self.selected_profile and self.selected_profile.casefold() not in names:
            raise ValidationError("Selected profile does not exist.")
        glossary_ids: set[str] = set()
        glossary_names: set[str] = set()
        for glossary in self.glossaries:
            glossary.validate()
            if glossary.id in glossary_ids:
                raise ValidationError(f'Duplicate glossary id: "{glossary.id}".')
            glossary_ids.add(glossary.id)
            name_key = glossary.name.casefold()
            if name_key in glossary_names:
                raise ValidationError(f'Duplicate glossary name: "{glossary.name}".')
            glossary_names.add(name_key)
        if self.selected_glossary_id and self.selected_glossary_id not in glossary_ids:
            raise ValidationError("Selected glossary does not exist.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "llama_cpp_folder": self.llama_cpp_folder,
            "model_folder": self.model_folder,
            "selected_profile": self.selected_profile,
            "startup_timeout_seconds": self.startup_timeout_seconds,
            "shutdown_timeout_seconds": self.shutdown_timeout_seconds,
            "profiles": [profile.to_dict() for profile in self.profiles],
            "interceptor_enabled": self.interceptor_enabled,
            "interceptor_host": self.interceptor_host,
            "interceptor_port": self.interceptor_port,
            "selected_glossary_id": self.selected_glossary_id,
            "glossaries": [glossary.to_dict() for glossary in self.glossaries],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        if not isinstance(data, dict):
            raise ValidationError("Settings root must be an object.")
        try:
            source_version = int(data.get("schema_version", 1))
            if source_version not in {1, SCHEMA_VERSION}:
                raise ValidationError(
                    f"Unsupported settings schema {source_version}; expected 1 or {SCHEMA_VERSION}."
                )
            settings = cls(
                schema_version=SCHEMA_VERSION,
                llama_cpp_folder=str(data.get("llama_cpp_folder", "")),
                model_folder=str(data.get("model_folder", "")),
                selected_profile=str(data.get("selected_profile", "")),
                startup_timeout_seconds=float(data.get("startup_timeout_seconds", 120)),
                shutdown_timeout_seconds=float(data.get("shutdown_timeout_seconds", 10)),
                profiles=[Profile.from_dict(item) for item in data.get("profiles", [])],
                interceptor_enabled=bool(data.get("interceptor_enabled", True)),
                interceptor_host=str(data.get("interceptor_host", "127.0.0.1")),
                interceptor_port=int(data.get("interceptor_port", 8081)),
                selected_glossary_id=str(data.get("selected_glossary_id", "")),
                glossaries=[
                    Glossary.from_dict(item) for item in data.get("glossaries", [])
                ],
            )
        except ValidationError:
            raise
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Invalid settings data: {exc}") from exc
        settings.validate(require_files=False)
        return settings


def _validate_host(host: str) -> None:
    if host in {"localhost", "0.0.0.0", "::"}:
        return
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    if len(host) > 253:
        raise ValidationError("Host is too long.")
    labels = host.rstrip(".").split(".")
    if not labels or any(
        not label
        or len(label) > 63
        or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
        for label in labels
    ):
        raise ValidationError("Host must be an IP address or valid hostname.")
