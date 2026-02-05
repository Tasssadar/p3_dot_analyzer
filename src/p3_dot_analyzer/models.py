from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


@dataclass(slots=True)
class NamedArea:
    """A named rectangular area on the image for analysis."""

    name: str
    x: int  # top-left x in image coords
    y: int  # top-left y in image coords
    width: int
    height: int


class NamedAreaData(TypedDict):
    name: str
    x: int
    y: int
    width: int
    height: int


class SettingsData(TypedDict, total=False):
    base_x: int | None
    base_y: int | None
    analysis_mode_enabled: bool
    color_tolerance: int
    min_area: int
    max_area: int
    min_circularity: float
    batch_sampling_rate: int
    named_areas: list[NamedAreaData]
    current_index: int
    active_tab: str
    selected_recording_name: str | None
    recording_frame_index: int
    render_temp_min: float
    render_temp_max: float
    render_colormap: str
    render_emissivity: float
    render_reflected_temp: float


@dataclass(slots=True)
class AreaPStatPoint:
    timestamp: float
    base_temp_c: float
    count_cur: int
    count_max: int
    frame_index: int


@dataclass(slots=True)
class BatchAnalysisResult:
    """Results from batch analysis of all images."""

    timestamps: list[float]  # seconds since start
    area_counts: dict[str, list[int]]  # area_name -> counts at each timestamp
    percentile_for_area: dict[int, dict[str, AreaPStatPoint]]
