"""Compatibility exports for Qt dashboard widgets."""

from .qt_ui.charts import CompactChart, _series_stats

series_stats = _series_stats

__all__ = ["CompactChart", "series_stats"]
