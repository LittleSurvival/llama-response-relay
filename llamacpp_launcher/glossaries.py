from __future__ import annotations

from copy import deepcopy

from .models import AppSettings, Glossary, ValidationError


class GlossaryService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def names(self) -> list[str]:
        return [glossary.name for glossary in self.settings.glossaries]

    def get(self, identifier: str) -> Glossary:
        key = identifier.casefold()
        for glossary in self.settings.glossaries:
            if glossary.id == identifier or glossary.name.casefold() == key:
                return glossary
        raise ValidationError(f'Glossary "{identifier}" does not exist.')

    def create(self, glossary: Glossary) -> Glossary:
        glossary.validate()
        self._ensure_unique_name(glossary.name)
        self._ensure_unique_id(glossary.id)
        self.settings.glossaries.append(glossary)
        self.settings.selected_glossary_id = glossary.id
        return glossary

    def update(self, glossary_id: str, glossary: Glossary) -> Glossary:
        existing = self.get(glossary_id)
        glossary.id = existing.id
        glossary.validate()
        self._ensure_unique_name(glossary.name, except_id=existing.id)
        index = self.settings.glossaries.index(existing)
        self.settings.glossaries[index] = glossary
        return glossary

    def rename(self, glossary_id: str, name: str) -> Glossary:
        existing = self.get(glossary_id)
        updated = deepcopy(existing)
        updated.name = name
        return self.update(glossary_id, updated)

    def select(self, glossary_id: str) -> Glossary:
        glossary = self.get(glossary_id)
        self.settings.selected_glossary_id = glossary.id
        return glossary

    def delete(self, glossary_id: str) -> None:
        glossary = self.get(glossary_id)
        self.settings.glossaries.remove(glossary)
        if self.settings.selected_glossary_id == glossary.id:
            self.settings.selected_glossary_id = (
                self.settings.glossaries[0].id if self.settings.glossaries else ""
            )

    def snapshot(self, glossary_id: str | None) -> Glossary | None:
        if not glossary_id:
            return None
        return deepcopy(self.get(glossary_id))

    def _ensure_unique_name(self, name: str, *, except_id: str = "") -> None:
        key = name.casefold()
        if any(
            glossary.name.casefold() == key and glossary.id != except_id
            for glossary in self.settings.glossaries
        ):
            raise ValidationError(f'Glossary name "{name}" is already in use.')

    def _ensure_unique_id(self, glossary_id: str) -> None:
        if any(item.id == glossary_id for item in self.settings.glossaries):
            raise ValidationError(f'Duplicate glossary id: "{glossary_id}".')
