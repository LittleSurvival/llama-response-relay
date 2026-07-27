from __future__ import annotations

from collections.abc import Callable


PALETTE = {
    "window": "#FFF8FC",
    "rail": "#FFF0F7",
    "surface": "#FFFFFF",
    "surface_alt": "#FDF2F8",
    "accent": "#E83E8C",
    "accent_hover": "#CF2D76",
    "accent_soft": "#FAD8E8",
    "text": "#2F242A",
    "muted": "#7B6872",
    "border": "#F0D7E3",
    "focus": "#B72E6E",
    "disabled": "#C7B8C0",
    "success": "#17846D",
    "success_soft": "#DDF5EE",
    "warning": "#A76300",
    "warning_soft": "#FFF0D0",
    "error": "#B72D49",
    "error_soft": "#FFE4EA",
    "log": "#241C21",
    "log_text": "#FFEAF4",
}

STATUS_COLORS = {
    "Stopped": (PALETTE["surface_alt"], PALETTE["muted"]),
    "Starting": (PALETTE["warning_soft"], PALETTE["warning"]),
    "Ready": (PALETTE["success_soft"], PALETTE["success"]),
    "Stopping": (PALETTE["warning_soft"], PALETTE["warning"]),
    "Failed": (PALETTE["error_soft"], PALETTE["error"]),
}


def ease_out_cubic(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 1 - (1 - value) ** 3


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def blend_color(start: str, end: str, amount: float) -> str:
    progress = ease_out_cubic(amount)
    start_rgb = hex_to_rgb(start)
    end_rgb = hex_to_rgb(end)
    values = [
        round(source + (target - source) * progress)
        for source, target in zip(start_rgb, end_rgb, strict=True)
    ]
    return "#{:02X}{:02X}{:02X}".format(*values)


class AfterAnimator:
    """Small cancellable animation runner using Tk's event loop."""

    def __init__(self, widget: object) -> None:
        self.widget = widget
        self._generation = 0

    def cancel(self) -> None:
        self._generation += 1

    def run(
        self,
        update: Callable[[float], None],
        *,
        duration_ms: int = 190,
        interval_ms: int = 16,
        complete: Callable[[], None] | None = None,
    ) -> None:
        self._generation += 1
        generation = self._generation
        steps = max(1, duration_ms // interval_ms)

        def tick(step: int) -> None:
            if generation != self._generation:
                return
            update(ease_out_cubic(step / steps))
            if step < steps:
                self.widget.after(interval_ms, tick, step + 1)
            elif complete is not None:
                complete()

        tick(0)
