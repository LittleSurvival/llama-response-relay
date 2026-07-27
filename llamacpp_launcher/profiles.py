from __future__ import annotations

from dataclasses import replace

from .models import AppSettings, Profile, ValidationError


class ProfileService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def names(self) -> list[str]:
        return [profile.name for profile in self.settings.profiles]

    def get(self, name: str) -> Profile:
        key = name.casefold()
        for profile in self.settings.profiles:
            if profile.name.casefold() == key:
                return profile
        raise ValidationError(f'Profile "{name}" does not exist.')

    def create(self, profile: Profile) -> Profile:
        profile.validate(self.settings.model_folder, require_files=True)
        self._ensure_unique(profile.name)
        self.settings.profiles.append(profile)
        self.settings.selected_profile = profile.name
        return profile

    def update(self, original_name: str, profile: Profile) -> Profile:
        profile.validate(self.settings.model_folder, require_files=True)
        existing = self.get(original_name)
        self._ensure_unique(profile.name, except_name=existing.name)
        index = self.settings.profiles.index(existing)
        self.settings.profiles[index] = profile
        if self.settings.selected_profile.casefold() == original_name.casefold():
            self.settings.selected_profile = profile.name
        return profile

    def duplicate(self, name: str) -> Profile:
        source = self.get(name)
        base = f"{source.name} Copy"
        candidate = base
        suffix = 2
        while self._contains(candidate):
            candidate = f"{base} {suffix}"
            suffix += 1
        copy = replace(source, name=candidate)
        self.settings.profiles.append(copy)
        self.settings.selected_profile = copy.name
        return copy

    def delete(self, name: str, *, running_profile: str | None = None) -> None:
        if running_profile and running_profile.casefold() == name.casefold():
            raise ValidationError("Stop the running profile before deleting it.")
        profile = self.get(name)
        self.settings.profiles.remove(profile)
        if self.settings.selected_profile.casefold() == name.casefold():
            self.settings.selected_profile = (
                self.settings.profiles[0].name if self.settings.profiles else ""
            )

    def select(self, name: str) -> Profile:
        profile = self.get(name)
        self.settings.selected_profile = profile.name
        return profile

    def _contains(self, name: str) -> bool:
        key = name.casefold()
        return any(profile.name.casefold() == key for profile in self.settings.profiles)

    def _ensure_unique(self, name: str, *, except_name: str | None = None) -> None:
        key = name.casefold()
        ignored = except_name.casefold() if except_name else None
        if any(
            profile.name.casefold() == key and profile.name.casefold() != ignored
            for profile in self.settings.profiles
        ):
            raise ValidationError(f'Profile name "{name}" is already in use.')
