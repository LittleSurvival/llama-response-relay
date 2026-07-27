from __future__ import annotations

import pytest

from llamacpp_launcher.models import Glossary, GlossaryEntry
from llamacpp_launcher.replacement import CompiledGlossary, IncrementalReplacer


def compile_entries(*entries: GlossaryEntry) -> CompiledGlossary:
    glossary = Glossary(name="Test", entries=list(entries))
    glossary.validate()
    return CompiledGlossary.from_glossary(glossary)


def test_longest_match_wins_and_replacement_is_not_reprocessed() -> None:
    compiled = compile_entries(
        GlossaryEntry(source="魔法", replacement="magic"),
        GlossaryEntry(source="魔法少女", replacement="魔法"),
        GlossaryEntry(source="magic", replacement="changed"),
    )

    assert compiled.replace("魔法少女和魔法") == "魔法和magic"


def test_case_modes_disabled_rules_and_unicode() -> None:
    compiled = compile_entries(
        GlossaryEntry(
            source="Llama", replacement="羊駝", case_sensitive=False
        ),
        GlossaryEntry(source="Alice", replacement="愛麗絲", case_sensitive=True),
        GlossaryEntry(source="disabled", replacement="X", enabled=False),
    )

    assert compiled.replace("LLAMA llama Alice alice disabled") == (
        "羊駝 羊駝 愛麗絲 alice disabled"
    )


@pytest.mark.parametrize(
    "chunks",
    [
        ["魔", "法", "少女"],
        ["魔法", "少", "女"],
        ["魔法少女"],
        ["魔", "法少女"],
    ],
)
def test_incremental_matching_across_arbitrary_boundaries(chunks: list[str]) -> None:
    compiled = compile_entries(
        GlossaryEntry(source="魔法", replacement="magic"),
        GlossaryEntry(source="魔法少女", replacement="magical girl"),
    )
    matcher = IncrementalReplacer(compiled)

    output = "".join(matcher.feed(chunk) for chunk in chunks)
    output += matcher.flush()

    assert output == "magical girl"
    assert len(matcher.pending) == 0


def test_incremental_flush_emits_unfinished_prefix() -> None:
    compiled = compile_entries(GlossaryEntry(source="llama", replacement="alpaca"))
    matcher = IncrementalReplacer(compiled)

    assert matcher.feed("lla") == ""
    assert matcher.flush() == "lla"


def test_equal_length_tie_uses_entry_order() -> None:
    compiled = compile_entries(
        GlossaryEntry(source="Test", replacement="first", case_sensitive=False),
        GlossaryEntry(source="test", replacement="second", case_sensitive=True),
    )
    assert compiled.replace("test") == "first"
