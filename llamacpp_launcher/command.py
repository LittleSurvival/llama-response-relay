from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import shlex
import subprocess

from .models import GpuMode, Profile, ValidationError


MANAGED_OPTIONS = {
    "-m",
    "--model",
    "--host",
    "--port",
    "-ngl",
    "--gpu-layers",
    "-c",
    "--ctx-size",
    "-np",
    "--parallel",
    "-fa",
    "--flash-attn",
    "--no-mmap",
    "--split-mode",
    "--metrics",
    "--no-metrics",
    "--slots",
    "--no-slots",
}


def parse_custom_args(value: str) -> list[str]:
    if not value.strip():
        return []
    if os.name == "nt":
        value = value.strip()
        if not _has_balanced_windows_quotes(value):
            raise ValidationError("Invalid custom arguments: unmatched double quote.")
        return _command_line_to_argv(value)
    try:
        return shlex.split(value, posix=True)
    except ValueError as exc:
        raise ValidationError(f"Invalid custom arguments: {exc}") from exc


def build_command(executable: Path, profile: Profile, help_text: str = "") -> list[str]:
    custom = parse_custom_args(profile.custom_args)
    _reject_managed_conflicts(custom)
    command = [
        str(executable),
        "-m",
        profile.model_path,
        "--host",
        profile.host,
        "--port",
        str(profile.port),
        "-ngl",
        str(profile.ngl),
        "-c",
        str(profile.context_size),
        "-np",
        str(profile.parallel_slots),
        "-fa",
        profile.flash_attention.value,
    ]
    if profile.no_mmap:
        command.append("--no-mmap")
    if profile.gpu_mode is not GpuMode.AUTO:
        if not supports_option(help_text, "--split-mode"):
            raise ValidationError(
                f'GPU mode "{profile.gpu_mode.value}" requires --split-mode support '
                "from the selected llama.cpp build."
            )
        command.extend(
            ["--split-mode", "none" if profile.gpu_mode is GpuMode.SINGLE else "layer"]
        )
    if supports_option(help_text, "--metrics"):
        command.append("--metrics")
    if supports_option(help_text, "--slots"):
        command.append("--slots")
    command.extend(custom)
    return command


def probe_help(executable: Path, timeout_seconds: float = 120.0) -> str:
    if timeout_seconds <= 0:
        raise ValidationError("Options inspection timeout must be positive.")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [str(executable), "--help"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
            shell=False,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationError(
            f"llama.cpp options inspection (--help) timed out after {timeout_seconds:g}s. "
            "The model has not started loading. Increase Startup timeout and try again."
        ) from exc
    except OSError as exc:
        raise ValidationError(f"Could not inspect llama.cpp options: {exc}") from exc
    if result.returncode != 0:
        raise ValidationError(
            f"llama.cpp options inspection (--help) exited with code {result.returncode}: "
            f"{result.stdout[-2000:]}"
        )
    return result.stdout


def supports_option(help_text: str, option: str) -> bool:
    return bool(re.search(rf"(?<!\S){re.escape(option)}(?:[=\s,]|$)", help_text))


def _reject_managed_conflicts(arguments: list[str]) -> None:
    for argument in arguments:
        option = argument.split("=", 1)[0].casefold()
        if option in MANAGED_OPTIONS:
            raise ValidationError(
                f'Custom option "{option}" conflicts with a structured profile field.'
            )


def _command_line_to_argv(value: str) -> list[str]:
    shell32 = ctypes.windll.shell32
    shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
    argc = ctypes.c_int()
    pointer = shell32.CommandLineToArgvW(value, ctypes.byref(argc))
    if not pointer:
        raise ValidationError("Invalid Windows custom argument string.")
    try:
        return [pointer[index] for index in range(argc.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(pointer)


def _has_balanced_windows_quotes(value: str) -> bool:
    quoted = False
    backslashes = 0
    for character in value:
        if character == "\\":
            backslashes += 1
            continue
        if character == '"' and backslashes % 2 == 0:
            quoted = not quoted
        backslashes = 0
    return not quoted
