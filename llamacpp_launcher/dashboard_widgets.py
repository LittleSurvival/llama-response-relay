from __future__ import annotations

import tkinter as tk
from typing import Iterable

import customtkinter as ctk

from .theme import PALETTE


def series_stats(values: Iterable[float | None]) -> tuple[float | None, float | None]:
    present = [float(value) for value in values if value is not None]
    if not present:
        return None, None
    return present[-1], max(present)


class CompactChart(ctk.CTkFrame):
    """Small two-series chart drawn by Tk without a plotting dependency."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        primary_label: str,
        secondary_label: str,
        *,
        primary_color: str = PALETTE["accent"],
        secondary_color: str = PALETTE["success"],
    ) -> None:
        super().__init__(
            parent,
            height=58,
            corner_radius=9,
            fg_color=PALETTE["surface_alt"],
            border_width=1,
            border_color=PALETTE["border"],
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self._primary_label = primary_label
        self._secondary_label = secondary_label
        self._primary_color = primary_color
        self._secondary_color = secondary_color
        self._primary: tuple[float | None, ...] = ()
        self._secondary: tuple[float | None, ...] = ()
        self._state = "Unavailable"

        ctk.CTkLabel(
            self,
            text=title,
            text_color=PALETTE["text"],
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=(9, 4), pady=(5, 0), sticky="w")
        self.meta = ctk.CTkLabel(
            self,
            text="Unavailable",
            text_color=PALETTE["muted"],
            font=ctk.CTkFont("Segoe UI", 8),
            anchor="e",
        )
        self.meta.grid(row=0, column=1, padx=(4, 9), pady=(5, 0), sticky="e")
        self.canvas = tk.Canvas(
            self,
            height=32,
            highlightthickness=0,
            bd=0,
            background=PALETTE["surface_alt"],
        )
        self.canvas.grid(
            row=1, column=0, columnspan=2, padx=7, pady=(1, 5), sticky="nsew"
        )
        self.canvas.bind("<Configure>", lambda _event: self._redraw())

    def set_data(
        self,
        primary: Iterable[float | None],
        secondary: Iterable[float | None],
        *,
        state: str,
    ) -> None:
        self._primary = tuple(primary)[-300:]
        self._secondary = tuple(secondary)[-300:]
        self._state = state
        primary_current, primary_peak = series_stats(self._primary)
        secondary_current, secondary_peak = series_stats(self._secondary)
        if primary_current is None and secondary_current is None:
            self.meta.configure(text=state)
        else:
            self.meta.configure(
                text=(
                    f"{self._primary_label} {self._format(primary_current)}"
                    f" · peak {self._format(primary_peak)}   "
                    f"{self._secondary_label} {self._format(secondary_current)}"
                    f" · peak {self._format(secondary_peak)}"
                )
            )
        self._redraw()

    @staticmethod
    def _format(value: float | None) -> str:
        if value is None:
            return "—"
        return f"{value:.1f}" if abs(value) < 1000 else f"{value / 1000:.1f}k"

    def _redraw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        for fraction in (0.25, 0.5, 0.75):
            y = height * fraction
            canvas.create_line(
                0, y, width, y, fill=PALETTE["border"], dash=(2, 4)
            )
        drew = False
        for values, color in (
            (self._primary, self._primary_color),
            (self._secondary, self._secondary_color),
        ):
            present = [value for value in values if value is not None]
            if not present:
                continue
            peak = max(max(present), 1e-9)
            count = max(2, len(values))
            points: list[float] = []
            for index, value in enumerate(values):
                if value is None:
                    if len(points) >= 4:
                        canvas.create_line(
                            *points, fill=color, width=2, smooth=True
                        )
                    points = []
                    continue
                x = index * width / (count - 1)
                y = height - 3 - (value / peak) * (height - 6)
                points.extend((x, y))
            if len(points) >= 4:
                canvas.create_line(*points, fill=color, width=2, smooth=True)
                drew = True
            elif len(points) == 2:
                x, y = points
                canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color, width=0)
                drew = True
        if not drew:
            canvas.create_text(
                width / 2,
                height / 2,
                text=self._state,
                fill=PALETTE["muted"],
                font=("Segoe UI", 8),
            )
