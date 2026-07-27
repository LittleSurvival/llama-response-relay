from __future__ import annotations

from pathlib import Path

import pytest

from llamacpp_launcher.command import build_command, parse_custom_args
from llamacpp_launcher.models import FlashAttention, GpuMode, Profile, ValidationError


def configured_profile(tmp_path: Path) -> Profile:
    model = tmp_path / "models" / "pink model.gguf"
    model.parent.mkdir()
    model.touch()
    return Profile(
        name="Pink",
        model_path=str(model),
        host="127.0.0.1",
        port=9090,
        ngl=42,
        context_size=8192,
        parallel_slots=3,
        flash_attention=FlashAttention.ON,
        no_mmap=True,
        custom_args='--threads 8 --alias "Pink Model"',
    )


def test_build_command_is_deterministic_and_preserves_spaces(tmp_path: Path) -> None:
    executable = tmp_path / "llama cpp" / "llama-server.exe"
    executable.parent.mkdir()
    executable.touch()
    profile = configured_profile(tmp_path)

    result = build_command(executable, profile)

    assert result[:5] == [
        str(executable),
        "-m",
        profile.model_path,
        "--host",
        "127.0.0.1",
    ]
    assert result.count("--no-mmap") == 1
    assert result[-4:] == ["--threads", "8", "--alias", "Pink Model"]


@pytest.mark.parametrize("argument", ["--port 9999", "--host=0.0.0.0", "-m other.gguf"])
def test_custom_arguments_cannot_override_structured_fields(
    tmp_path: Path, argument: str
) -> None:
    profile = configured_profile(tmp_path)
    profile.custom_args = argument

    with pytest.raises(ValidationError, match="conflicts"):
        build_command(tmp_path / "llama-server.exe", profile)


def test_gpu_auto_emits_no_split_mode(tmp_path: Path) -> None:
    profile = configured_profile(tmp_path)
    profile.gpu_mode = GpuMode.AUTO

    assert "--split-mode" not in build_command(tmp_path / "llama-server.exe", profile)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [(GpuMode.SINGLE, "none"), (GpuMode.MULTI, "layer")],
)
def test_explicit_gpu_modes_require_and_use_split_mode(
    tmp_path: Path, mode: GpuMode, expected: str
) -> None:
    profile = configured_profile(tmp_path)
    profile.gpu_mode = mode

    with pytest.raises(ValidationError, match="split-mode"):
        build_command(tmp_path / "llama-server.exe", profile, "--host HOST")

    command = build_command(
        tmp_path / "llama-server.exe", profile, "--split-mode {none,layer,row}"
    )
    index = command.index("--split-mode")
    assert command[index + 1] == expected


def test_invalid_custom_quote_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_custom_args('--alias "unterminated')


def test_supported_dashboard_endpoints_are_enabled_once(tmp_path: Path) -> None:
    profile = configured_profile(tmp_path)
    command = build_command(
        tmp_path / "llama-server.exe",
        profile,
        "--metrics enable metrics\n--slots enable slots",
    )

    assert command.count("--metrics") == 1
    assert command.count("--slots") == 1


@pytest.mark.parametrize(
    "argument",
    ["--metrics", "--no-metrics", "--slots", "--no-slots"],
)
def test_custom_arguments_cannot_override_dashboard_endpoints(
    tmp_path: Path, argument: str
) -> None:
    profile = configured_profile(tmp_path)
    profile.custom_args = argument

    with pytest.raises(ValidationError, match="conflicts"):
        build_command(tmp_path / "llama-server.exe", profile, "--metrics\n--slots")
