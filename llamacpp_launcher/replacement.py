from __future__ import annotations

from dataclasses import dataclass

from .models import Glossary, GlossaryEntry


@dataclass(frozen=True, slots=True)
class ReplacementRule:
    source: str
    replacement: str
    case_sensitive: bool
    order: int

    def matches(self, value: str) -> bool:
        if len(value) < len(self.source):
            return False
        candidate = value[: len(self.source)]
        if self.case_sensitive:
            return candidate == self.source
        return candidate.casefold() == self.source.casefold()

    def starts_with(self, value: str) -> bool:
        if len(value) >= len(self.source):
            return False
        prefix = self.source[: len(value)]
        if self.case_sensitive:
            return prefix == value
        return prefix.casefold() == value.casefold()


@dataclass(frozen=True, slots=True)
class CompiledGlossary:
    rules: tuple[ReplacementRule, ...]
    max_source_length: int

    @classmethod
    def from_glossary(cls, glossary: Glossary | None) -> CompiledGlossary:
        entries: list[GlossaryEntry] = [] if glossary is None else glossary.entries
        rules = tuple(
            sorted(
                (
                    ReplacementRule(
                        source=entry.source,
                        replacement=entry.replacement,
                        case_sensitive=entry.case_sensitive,
                        order=index,
                    )
                    for index, entry in enumerate(entries)
                    if entry.enabled
                ),
                key=lambda rule: (-len(rule.source), rule.order),
            )
        )
        return cls(
            rules=rules,
            max_source_length=max((len(rule.source) for rule in rules), default=0),
        )

    def replace(self, text: str) -> str:
        matcher = IncrementalReplacer(self)
        return matcher.feed(text, final=True)


class IncrementalReplacer:
    def __init__(self, glossary: CompiledGlossary) -> None:
        self.glossary = glossary
        self.pending = ""

    def feed(self, text: str, *, final: bool = False) -> str:
        self.pending += text
        output: list[str] = []
        rules = self.glossary.rules
        while self.pending:
            full_match = next((rule for rule in rules if rule.matches(self.pending)), None)
            if full_match is not None:
                if not final and any(
                    len(rule.source) > len(full_match.source)
                    and rule.starts_with(self.pending)
                    for rule in rules
                ):
                    break
                output.append(full_match.replacement)
                self.pending = self.pending[len(full_match.source) :]
                continue
            if not final and any(rule.starts_with(self.pending) for rule in rules):
                break
            output.append(self.pending[0])
            self.pending = self.pending[1:]
        return "".join(output)

    def flush(self) -> str:
        return self.feed("", final=True)
