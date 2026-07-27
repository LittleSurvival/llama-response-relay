from __future__ import annotations

from dataclasses import dataclass

from ..models import AppSettings, FlashAttention, GpuMode, Profile, ValidationError
from ..process import RuntimeState
from ..telemetry import Availability


@dataclass(frozen=True, slots=True)
class ControlStates:
    start: bool
    stop: bool
    restart: bool


def control_states(
    state: RuntimeState, *, has_profile: bool, process_active: bool
) -> ControlStates:
    busy = state in {RuntimeState.STARTING, RuntimeState.STOPPING}
    return ControlStates(
        start=has_profile and not process_active and not busy,
        stop=process_active and state is not RuntimeState.STOPPING,
        restart=has_profile and process_active and state is not RuntimeState.STOPPING,
    )


def context_per_slot_text(context_size: int | str, parallel_slots: int | str) -> str:
    try:
        context = int(context_size)
        slots = int(parallel_slots)
    except (TypeError, ValueError):
        return ""
    if context <= 0 or slots <= 1:
        return ""
    per_slot = context // slots
    return f"≈ {per_slot:,} context per slot ({context:,} ÷ {slots})"


def endpoint_text(host: str, port: int | str, *, enabled: bool = True) -> str:
    if not enabled:
        return "Unavailable (LRR disabled)"
    try:
        port_number = int(port)
    except (TypeError, ValueError):
        return "Unavailable"
    host = host.strip()
    if not host or not 1 <= port_number <= 65535:
        return "Unavailable"
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{display_host}:{port_number}"


def availability_text(state: Availability, value: str) -> str:
    return value if state is Availability.AVAILABLE else state.value


def per_active_slot_rate(
    total_tokens_per_second: float | None, active_slots: int | None
) -> float | None:
    if (
        total_tokens_per_second is None
        or active_slots is None
        or active_slots <= 0
    ):
        return None
    return total_tokens_per_second / active_slots


def profile_from_values(
    *,
    name: str,
    model_path: str,
    host: str,
    port: str | int,
    ngl: str | int,
    context_size: str | int,
    parallel_slots: str | int,
    flash_attention: str,
    no_mmap: bool,
    gpu_mode: str,
    custom_args: str,
) -> Profile:
    try:
        return Profile(
            name=name.strip(),
            model_path=model_path,
            host=host.strip(),
            port=int(port),
            ngl=int(ngl),
            context_size=int(context_size),
            parallel_slots=int(parallel_slots),
            flash_attention=FlashAttention(flash_attention),
            no_mmap=no_mmap,
            gpu_mode=GpuMode(gpu_mode),
            custom_args=custom_args,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Numeric and option fields must contain valid values: {exc}"
        ) from exc


def clone_settings(settings: AppSettings) -> AppSettings:
    """Create a validated schema-preserving snapshot for rollback and tests."""
    return AppSettings.from_dict(settings.to_dict())
