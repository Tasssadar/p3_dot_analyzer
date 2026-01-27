from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Timer
from typing import TypedDict
from p3_viewer import ColormapID  # type: ignore

from .camera import CamFrame, RecordingReader

IMAGES_PER_SECOND = 25


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
    selected_color: list[int] | None
    analysis_mode_enabled: bool
    color_tolerance: int
    min_area: int
    min_circularity: float
    batch_sampling_rate: int
    named_areas: list[NamedAreaData]
    current_index: int
    render_temp_min: float
    render_temp_max: float
    render_colormap: str


@dataclass(slots=True)
class BatchAnalysisResult:
    """Results from batch analysis of all images."""

    timestamps: list[float]  # image_index / IMAGES_PER_SECOND
    area_counts: dict[str, list[int]]  # area_name -> counts at each timestamp


@dataclass(slots=True)
class AppState:
    texture_tag: str
    recording_texture_tag: str
    image_drawlist_tag: str
    image_draw_tag: str
    slider_tag: str
    filename_text_tag: str
    status_text_tag: str
    timestamp_text_tag: str = "timestamp_text"
    current_frame: CamFrame | None = None
    render_temp_min: float = 0.0
    render_temp_max: float = 35.0
    render_colormap: ColormapID = ColormapID.WHITE_HOT
    render_temp_min_input_tag: str = "render_temp_min_input"
    render_temp_max_input_tag: str = "render_temp_max_input"
    render_colormap_combo_tag: str = "render_colormap_combo"
    # Color picker state
    selected_color: tuple[int, int, int] | None = (163, 163, 163)
    color_swatch_tag: str = "color_swatch"
    color_text_tag: str = "color_text"
    # Named areas state
    named_areas: list[NamedArea] = field(default_factory=list)
    interaction_mode: str = "view"  # "view" or "create_area"
    drag_start: tuple[float, float] | None = None
    mode_button_tag: str = "mode_button"
    preview_rect_tag: str = "preview_rect"
    areas_list_tag: str = "areas_list"
    area_overlay_tags: list[str] = field(default_factory=list)
    # Analysis mode state
    analysis_mode_enabled: bool = True
    analysis_checkbox_tag: str = "analysis_checkbox"
    analysis_overlay_tags: list[str] = field(default_factory=list)
    area_mark_counts: dict[str, int] = field(default_factory=dict)
    color_tolerance: int = 30  # HSV tolerance for color matching
    min_area: int = 200  # Minimum contour area for mark detection
    min_circularity: float = 0.5  # Minimum circularity for mark detection
    tolerance_input_tag: str = "tolerance_input"
    min_area_input_tag: str = "min_area_input"
    min_circularity_input_tag: str = "min_circularity_input"
    # Batch analysis state
    batch_result: BatchAnalysisResult | None = None
    batch_sampling_rate: int = 5
    batch_sampling_input_tag: str = "batch_sampling_input"
    batch_analyze_button_tag: str = "batch_analyze_button"
    batch_chart_window_tag: str = "batch_chart_window"
    batch_plot_tag: str = "batch_plot"
    # Recording / playback UI state
    recording_active: bool = False
    recording_paused: bool = False
    current_recording_path: Path | None = None
    selected_recording_path: Path | None = None
    recording_reader: RecordingReader | None = None
    recording_frame_index: int = 0
    recording_frame_count: int = 0
    recording_frame_text_tag: str = "recording_frame_text"
    recording_selected_theme: int | None = None
    recordings_dir: Path | None = None
    recordings_list_tag: str = "recordings_list"
    recording_drawlist_tag: str = "recording_drawlist"
    recording_draw_tag: str = "recording_draw"
    recording_status_tag: str = "recording_status_text"
    recording_frame_period_ms: int = 500
    recording_frame_period_input_tag: str = "recording_frame_period_input"
    recording_start_button_tag: str = "recording_start_button"
    recording_pause_button_tag: str = "recording_pause_button"
    recording_stop_button_tag: str = "recording_stop_button"
    rename_modal_tag: str = "rename_recording_modal"
    rename_input_tag: str = "rename_recording_input"
    active_tab: str = "analysis_tab"
    camera_connected: bool = False
    # Settings persistence
    settings_path: Path | None = None
    settings_save_timer: Timer | None = None
