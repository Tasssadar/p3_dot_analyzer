from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Timer

from p3_viewer import ColormapID  # type: ignore

from .camera import CamFrame, RecordingReader
from .constants import (
    DEFAULT_BATCH_SAMPLING_RATE,
    DEFAULT_COLOR_TOLERANCE,
    DEFAULT_MIN_AREA,
    DEFAULT_MIN_CIRCULARITY,
    DEFAULT_RENDER_TEMP_MAX,
    DEFAULT_RENDER_TEMP_MIN,
    DEFAULT_RENDER_EMISSIVITY,
    DEFAULT_RENDER_REFLECTED_TEMP,
    DEFAULT_RECORDING_FRAME_PERIOD_MS,
    DEFAULT_ANALYSIS_ENABLED,
)
from .models import BatchAnalysisResult, NamedArea
from .render import RenderConfig


@dataclass(slots=True)
class UiState:
    texture_tag: str
    recording_texture_tag: str
    image_drawlist_tag: str
    image_draw_tag: str
    status_text_tag: str
    timestamp_text_tag: str = "timestamp_text"
    hover_temp_text_tag: str = "hover_temp_text"
    color_swatch_tag: str = "color_swatch"
    color_text_tag: str = "color_text"
    active_tab: str = "recording_tab"


@dataclass(slots=True)
class RenderState:
    current_frame: CamFrame | None = None
    temp_min: float = DEFAULT_RENDER_TEMP_MIN
    temp_max: float = DEFAULT_RENDER_TEMP_MAX
    colormap: ColormapID = ColormapID.WHITE_HOT
    emissivity: float = DEFAULT_RENDER_EMISSIVITY
    reflected_temp: float = DEFAULT_RENDER_REFLECTED_TEMP
    temp_min_input_tag: str = "render_temp_min_input"
    temp_max_input_tag: str = "render_temp_max_input"
    colormap_combo_tag: str = "render_colormap_combo"
    emissivity_input_tag: str = "render_emissivity_input"
    reflected_temp_input_tag: str = "render_reflected_temp_input"


@dataclass(slots=True)
class AnalysisState:
    selected_temp: float | None = None
    enabled: bool = DEFAULT_ANALYSIS_ENABLED
    checkbox_tag: str = "analysis_checkbox"
    overlay_tags: list[str] = field(default_factory=list)
    area_mark_counts: dict[str, int] = field(default_factory=dict)
    color_tolerance: int = DEFAULT_COLOR_TOLERANCE
    min_area: int = DEFAULT_MIN_AREA
    min_circularity: float = DEFAULT_MIN_CIRCULARITY
    tolerance_input_tag: str = "tolerance_input"
    min_area_input_tag: str = "min_area_input"
    min_circularity_input_tag: str = "min_circularity_input"
    batch_result: BatchAnalysisResult | None = None
    batch_sampling_rate: int = DEFAULT_BATCH_SAMPLING_RATE
    batch_sampling_input_tag: str = "batch_sampling_input"
    batch_analyze_button_tag: str = "batch_analyze_button"
    batch_chart_window_tag: str = "batch_chart_window"
    batch_plot_tag: str = "batch_plot"


@dataclass(slots=True)
class AreasState:
    named_areas: list[NamedArea] = field(default_factory=list)
    interaction_mode: str = "view"  # "view" or "create_area"
    drag_start: tuple[float, float] | None = None
    mode_button_tag: str = "mode_button"
    preview_rect_tag: str = "preview_rect"
    areas_list_tag: str = "areas_list"
    area_overlay_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RecordingState:
    active: bool = False
    paused: bool = False
    current_recording_path: Path | None = None
    selected_recording_path: Path | None = None
    reader: RecordingReader | None = None
    frame_index: int = 0
    frame_count: int = 0
    frame_text_tag: str = "recording_frame_text"
    selected_theme: int | None = None
    recordings_dir: Path | None = None
    recordings_list_tag: str = "recordings_list"
    drawlist_tag: str = "recording_drawlist"
    draw_tag: str = "recording_draw"
    status_tag: str = "recording_status_text"
    frame_period_ms: int = DEFAULT_RECORDING_FRAME_PERIOD_MS
    frame_period_input_tag: str = "recording_frame_period_input"
    start_button_tag: str = "recording_start_button"
    pause_button_tag: str = "recording_pause_button"
    stop_button_tag: str = "recording_stop_button"
    rename_modal_tag: str = "rename_recording_modal"
    rename_input_tag: str = "rename_recording_input"
    slider_tag: str = "image_slider"


@dataclass(slots=True)
class SettingsState:
    path: Path | None = None
    save_timer: Timer | None = None


@dataclass(slots=True)
class AppState:
    ui: UiState
    render: RenderState = field(default_factory=RenderState)
    analysis: AnalysisState = field(default_factory=AnalysisState)
    areas: AreasState = field(default_factory=AreasState)
    recording: RecordingState = field(default_factory=RecordingState)
    settings: SettingsState = field(default_factory=SettingsState)
    camera_connected: bool = False

    def build_render_config(self) -> RenderConfig:
        return RenderConfig(
            temp_min=self.render.temp_min,
            temp_max=self.render.temp_max,
            colormap=self.render.colormap,
        )
