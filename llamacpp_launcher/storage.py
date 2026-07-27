from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .models import AppSettings, ValidationError


APP_DIRECTORY = "LlamaCppLauncher"
SETTINGS_FILENAME = "settings.json"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()
        self.last_valid = AppSettings()

    def load(self) -> AppSettings:
        if not self.path.exists():
            self.last_valid = AppSettings()
            return self.last_valid
        try:
            raw = self.path.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
            loaded = AppSettings.from_dict(data)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ValidationError(f"Could not load settings from {self.path}: {exc}") from exc
        self.last_valid = loaded
        return loaded

    def save(self, settings: AppSettings) -> None:
        settings.validate(require_files=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n"
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f"{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            raise ValidationError(f"Could not save settings to {self.path}: {exc}") from exc
        self.last_valid = settings


def default_settings_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / APP_DIRECTORY / SETTINGS_FILENAME
