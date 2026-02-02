from __future__ import annotations

from pathlib import Path
import logging
import os

import dearpygui.dearpygui as dpg  # type: ignore

from .models import NamedArea

from .camera import (
    RENDER_HEIGHT,
    RENDER_WIDTH,
    Camera,
    CamEvRecordingStats,
    CamEvVersion,
    CamEvConnectFailed,
)
from .render import RenderConfig
from .settings_io import apply_settings_to_state, get_settings_path, load_settings
from .state import AppState, SettingsState, UiState
from .ui.app import build_ui
from .ui.recording_panel import update_recording_buttons, update_recording_indicator
from .ui_helpers import render_frame, update_recording_camera_status


def run() -> None:
    """Application entry point that sets up and runs the Dear PyGui app."""
    base_dir = Path(os.getcwd())
    settings_path = get_settings_path(base_dir)

    logging.basicConfig(level=logging.DEBUG)

    dpg.create_context()

    texture_tag = "analysis_texture"
    recording_texture_tag = "recording_texture"
    app_state = AppState(
        ui=UiState(
            texture_tag=texture_tag,
            recording_texture_tag=recording_texture_tag,
            image_drawlist_tag="image_drawlist",
            image_draw_tag="image_draw",
            status_text_tag="status_text",
        ),
        settings=SettingsState(path=settings_path),
    )
    app_state.recording.recordings_dir = base_dir / "recordings"

    # Add default areas
    app_state.analysis.base_x = 466
    app_state.analysis.base_y = 192
    app_state.areas.named_areas.append(
        NamedArea(name="Smes", x=60, y=206, width=411, height=63)
    )
    app_state.areas.named_areas.append(
        NamedArea(name="Voda", x=60, y=277, width=420, height=65)
    )

    camera = Camera()

    settings = load_settings(settings_path)
    if settings is not None:
        apply_settings_to_state(app_state, settings)
        selected_name = settings.get("selected_recording_name")
        if isinstance(selected_name, str) and selected_name:
            candidate = app_state.recording.recordings_dir / selected_name
            if candidate.exists():
                app_state.recording.selected_recording_path = candidate
            else:
                app_state.recording.selected_recording_path = None
                app_state.recording.frame_index = 0

    if app_state.render.temp_max <= app_state.render.temp_min:
        app_state.render.temp_max = app_state.render.temp_min + 0.1
    camera.set_render_config(
        RenderConfig(
            temp_min=app_state.render.temp_min,
            temp_max=app_state.render.temp_max,
            colormap=app_state.render.colormap,
        )
    )

    with dpg.texture_registry():
        dpg.add_dynamic_texture(
            RENDER_WIDTH,
            RENDER_HEIGHT,
            [0] * RENDER_WIDTH * RENDER_HEIGHT * 4,
            tag=texture_tag,
        )
        dpg.add_dynamic_texture(
            RENDER_WIDTH,
            RENDER_HEIGHT,
            [0] * RENDER_WIDTH * RENDER_HEIGHT * 4,
            tag=recording_texture_tag,
        )

    build_ui(app_state, camera)
    dpg.create_viewport(title="P3 Camera Tecky - Image Viewer", width=1700, height=950)
    dpg.set_viewport_vsync(True)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)

    camera.start()

    try:
        while dpg.is_dearpygui_running():
            ev = camera.get_event()
            match ev:
                case CamEvVersion():
                    app_state.camera_connected = True
                    update_recording_camera_status(
                        app_state, f"Camera connected: {ev.name} {ev.version}"
                    )
                    update_recording_buttons(app_state)
                case CamEvConnectFailed():
                    app_state.camera_connected = False
                    update_recording_camera_status(
                        app_state, f"Connect failed: {ev.message}"
                    )
                    update_recording_buttons(app_state)
                case CamEvRecordingStats():
                    if app_state.recording.active:
                        status_label = (
                            "Paused" if app_state.recording.paused else "Recording"
                        )
                    else:
                        status_label = "Idle"
                    update_recording_indicator(app_state, status_label, ev)

            frame = camera.take_frame()

            if app_state.ui.active_tab == "recording_tab" and frame is not None:
                render_frame(
                    app_state,
                    frame,
                    texture_tag=app_state.ui.recording_texture_tag,
                    draw_tag=app_state.recording.draw_tag,
                    update_timestamp=False,
                )

            dpg.render_dearpygui_frame()
    finally:
        camera.stop()
        dpg.destroy_context()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
