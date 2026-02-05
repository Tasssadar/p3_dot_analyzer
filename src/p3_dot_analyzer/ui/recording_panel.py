from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import os

import dearpygui.dearpygui as dpg  # type: ignore

from collections.abc import Callable

from ..camera import (
    RENDER_HEIGHT,
    RENDER_WIDTH,
    Camera,
    RecordingReader,
    CamEvRecordingStats,
)
from ..state import AppState
from ..settings_io import schedule_settings_save
from ..ui_helpers import render_frame, update_status


def format_duration(duration: timedelta) -> str:
    total_seconds = int(duration.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_bytes(size_bytes: int) -> str:
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(size_bytes)} B"


def update_recording_indicator(
    state: AppState, status_label: str, stats: CamEvRecordingStats | None = None
) -> None:
    if stats is None:
        text = status_label
    else:
        duration_text = format_duration(stats.duration)
        size_text = format_bytes(stats.file_size_bytes)
        text = f"{status_label} | {duration_text} | {stats.frame_count} frames | {size_text}"
    dpg.set_value(state.recording.status_tag, text)


def update_recording_buttons(state: AppState) -> None:
    start_enabled = state.camera_connected and (
        not state.recording.active or state.recording.paused
    )
    pause_enabled = state.recording.active
    stop_enabled = state.recording.active
    dpg.configure_item(state.recording.start_button_tag, enabled=start_enabled)
    dpg.configure_item(state.recording.pause_button_tag, enabled=pause_enabled)
    dpg.configure_item(state.recording.stop_button_tag, enabled=stop_enabled)


def update_recording_frame_text(state: AppState) -> None:
    if not dpg.does_item_exist(state.recording.frame_text_tag):
        return
    if state.recording.frame_count <= 0:
        dpg.set_value(state.recording.frame_text_tag, "No recording loaded")
        return
    label = f"Frame {state.recording.frame_index + 1}/{state.recording.frame_count}"
    if state.recording.reader is not None and state.render.current_frame is not None:
        ts_start = state.recording.reader.ts_start.timestamp()
        elapsed_seconds = max(0.0, state.render.current_frame.ts - ts_start)
        label = f"{label} | t={elapsed_seconds:.2f}s"
    dpg.set_value(state.recording.frame_text_tag, label)


def render_recording_frame(
    state: AppState,
    index: int,
    on_image_loaded: Callable[[AppState], None] | None = None,
) -> None:
    if state.recording.reader is None:
        return
    if state.recording.frame_count <= 0:
        return
    index = max(0, min(state.recording.frame_count - 1, index))
    state.recording.frame_index = index
    if dpg.does_item_exist(state.recording.slider_tag):
        dpg.set_value(state.recording.slider_tag, index)
    config = state.build_render_config()
    state.render.current_frame = state.recording.reader.read_frame(index, config)
    render_frame(
        state,
        state.render.current_frame,
        texture_tag=state.ui.texture_tag,
        draw_tag=state.ui.image_draw_tag,
        on_image_loaded=on_image_loaded,
    )
    update_recording_frame_text(state)


def close_recording_reader(state: AppState) -> None:
    if state.recording.reader is not None:
        state.recording.reader.close()
        state.recording.reader = None
    state.recording.frame_count = 0
    state.recording.frame_index = 0
    if dpg.does_item_exist(state.recording.slider_tag):
        dpg.configure_item(
            state.recording.slider_tag, enabled=False, min_value=0, max_value=0
        )
        dpg.set_value(state.recording.slider_tag, 0)
    update_recording_frame_text(state)


def open_selected_recording(
    state: AppState, on_image_loaded: Callable[[AppState], None] | None = None
) -> None:
    if state.recording.reader is not None:
        state.recording.reader.close()
        state.recording.reader = None

    target = state.recording.selected_recording_path
    if target is None:
        close_recording_reader(state)
        return
    if state.recording.active and state.recording.current_recording_path == target:
        update_status(state, "Recording is active; stop it to analyze.")
        close_recording_reader(state)
        return

    try:
        reader = RecordingReader(target)
    except OSError as exc:
        update_status(state, f"Failed to open recording: {exc}")
        close_recording_reader(state)
        return

    if reader.frame_count == 0:
        reader.close()
        update_status(state, "Recording is empty.")
        close_recording_reader(state)
        return

    state.recording.reader = reader
    state.recording.frame_count = reader.frame_count
    saved_index = state.recording.frame_index
    state.recording.frame_index = max(
        0, min(state.recording.frame_count - 1, saved_index)
    )
    if dpg.does_item_exist(state.recording.slider_tag):
        dpg.configure_item(
            state.recording.slider_tag,
            enabled=True,
            min_value=0,
            max_value=state.recording.frame_count - 1,
        )
    render_recording_frame(state, state.recording.frame_index, on_image_loaded)


def get_recordings_dir(state: AppState) -> Path:
    if state.recording.recordings_dir is None:
        state.recording.recordings_dir = Path(os.getcwd()) / "recordings"
    return state.recording.recordings_dir


def list_recordings(state: AppState) -> list[Path]:
    recordings_dir = get_recordings_dir(state)
    if not recordings_dir.exists():
        return []
    return sorted(recordings_dir.glob("*.p3dat"), key=lambda p: p.name.lower())


def refresh_recordings_list(
    state: AppState, on_image_loaded: Callable[[AppState], None] | None = None
) -> None:
    if not dpg.does_item_exist(state.recording.recordings_list_tag):
        return
    dpg.delete_item(state.recording.recordings_list_tag, children_only=True)
    recordings = list_recordings(state)
    if not recordings:
        dpg.add_text("No recordings found", parent=state.recording.recordings_list_tag)
        return
    for rec_path in recordings:
        is_selected = state.recording.selected_recording_path == rec_path

        def on_select(_sender: int, app_data: bool, user_data: Path) -> None:
            if not app_data:
                return
            state.recording.selected_recording_path = user_data
            state.recording.frame_index = 0
            schedule_settings_save(state)
            update_status(state, f"Selected recording: {user_data.name}")
            open_selected_recording(state, on_image_loaded)
            refresh_recordings_list(state, on_image_loaded)

        with dpg.group(horizontal=True, parent=state.recording.recordings_list_tag):
            dpg.add_selectable(
                label=f"▶ {rec_path.name}" if is_selected else rec_path.name,
                default_value=is_selected,
                callback=on_select,
                user_data=rec_path,
                width=210,
            )
            if is_selected and state.recording.selected_theme is not None:
                dpg.bind_item_theme(dpg.last_item(), state.recording.selected_theme)

            def on_rename_clicked(
                _sender: int, _app_data: None, user_data: Path
            ) -> None:
                if (
                    state.recording.active
                    and state.recording.current_recording_path == user_data
                ):
                    update_status(state, "Cannot rename the active recording.")
                    return
                show_rename_modal(state, user_data, on_image_loaded)

            def on_delete_clicked(
                _sender: int, _app_data: None, user_data: Path
            ) -> None:
                if (
                    state.recording.active
                    and state.recording.current_recording_path == user_data
                ):
                    update_status(state, "Cannot delete the active recording.")
                    return
                try:
                    if user_data.exists():
                        user_data.unlink()
                    if state.recording.selected_recording_path == user_data:
                        state.recording.selected_recording_path = None
                        close_recording_reader(state)
                        schedule_settings_save(state)
                    update_status(state, f"Deleted recording: {user_data.name}")
                except OSError as exc:
                    update_status(
                        state,
                        f"Failed to delete recording: {user_data.name} ({exc})",
                    )
                refresh_recordings_list(state, on_image_loaded)

            dpg.add_button(
                label="Rename",
                callback=on_rename_clicked,
                user_data=rec_path,
                width=60,
            )
            dpg.add_button(
                label="Delete",
                callback=on_delete_clicked,
                user_data=rec_path,
                width=55,
            )


def show_rename_modal(
    state: AppState,
    target_path: Path,
    on_image_loaded: Callable[[AppState], None] | None = None,
) -> None:
    if dpg.does_item_exist(state.recording.rename_modal_tag):
        dpg.delete_item(state.recording.rename_modal_tag)

    def on_confirm(_sender: int, _app_data: None) -> None:
        new_name = dpg.get_value(state.recording.rename_input_tag).strip()
        if not new_name:
            update_status(state, "Recording name cannot be empty.")
            return
        if any(sep in new_name for sep in ("/", "\\")):
            update_status(state, "Recording name cannot contain path separators.")
            return
        recordings_dir = get_recordings_dir(state)
        new_path = recordings_dir / f"{new_name}{target_path.suffix}"
        if new_path.exists():
            update_status(state, "A recording with that name already exists.")
            return
        try:
            target_path.rename(new_path)
            if state.recording.selected_recording_path == target_path:
                state.recording.selected_recording_path = new_path
                schedule_settings_save(state)
                open_selected_recording(state, on_image_loaded)
            update_status(state, f"Renamed recording to: {new_path.name}")
        except OSError as exc:
            update_status(
                state, f"Failed to rename recording: {target_path.name} ({exc})"
            )
        dpg.delete_item(state.recording.rename_modal_tag)
        refresh_recordings_list(state, on_image_loaded)

    def on_cancel(_sender: int, _app_data: None) -> None:
        dpg.delete_item(state.recording.rename_modal_tag)

    with dpg.window(
        label="Rename Recording",
        tag=state.recording.rename_modal_tag,
        modal=True,
        no_close=True,
        pos=(400, 300),
        width=320,
        height=140,
    ):
        dpg.add_text(f"Current: {target_path.name}")
        dpg.add_input_text(
            label="New name",
            tag=state.recording.rename_input_tag,
            default_value=target_path.stem,
            width=220,
        )
        with dpg.group(horizontal=True):
            dpg.add_button(label="Rename", callback=on_confirm)
            dpg.add_button(label="Cancel", callback=on_cancel)


def build_recording_tab(
    state: AppState,
    camera: Camera,
    on_image_loaded: Callable[[AppState], None] | None = None,
) -> None:
    with dpg.group(horizontal=True):
        with dpg.group():
            dpg.add_text("Camera")
            with dpg.drawlist(
                width=RENDER_WIDTH,
                height=RENDER_HEIGHT,
                tag=state.recording.drawlist_tag,
            ):
                dpg.draw_image(
                    state.ui.recording_texture_tag,
                    pmin=(0, 0),
                    pmax=(1, 1),  # updated on render
                    tag=state.recording.draw_tag,
                )
            dpg.add_text("Camera status: --", tag=state.recording.camera_status_tag)
        with dpg.group():
            dpg.add_text("Recording Controls")
            dpg.add_separator()
            dpg.add_text("Idle", tag=state.recording.status_tag)
            dpg.add_input_int(
                label="Frame period (ms)",
                default_value=state.recording.frame_period_ms,
                min_value=1,
                max_value=10000,
                min_clamped=True,
                max_clamped=True,
                callback=lambda _s, v: setattr(
                    state.recording, "frame_period_ms", max(1, min(10000, int(v)))
                ),
                tag=state.recording.frame_period_input_tag,
                width=140,
            )

            def on_start_recording(_sender: int, _app_data: None) -> None:
                if not state.camera_connected:
                    update_status(
                        state,
                        "Camera not connected. Connect the camera first.",
                    )
                    return
                if state.recording.active:
                    update_status(state, "Recording already in progress.")
                    return
                recordings_dir = get_recordings_dir(state)
                recordings_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                recording_path = recordings_dir / f"recording_{timestamp}.p3dat"
                frame_period = timedelta(milliseconds=state.recording.frame_period_ms)
                try:
                    camera.start_recording(recording_path, frame_period)
                except ValueError as exc:
                    update_status(state, f"Recording start failed: {exc}")
                    return
                state.recording.current_recording_path = recording_path
                state.recording.active = True
                state.recording.paused = False
                dpg.configure_item(state.recording.pause_button_tag, label="Pause")
                update_recording_buttons(state)
                update_recording_indicator(state, "Recording")
                update_status(state, f"Recording started: {recording_path.name}")

            def on_pause_recording(_sender: int, _app_data: None) -> None:
                if not state.recording.active:
                    update_status(state, "No active recording to pause.")
                    return
                state.recording.paused = not state.recording.paused
                camera.pause_recording(state.recording.paused)
                dpg.configure_item(
                    state.recording.pause_button_tag,
                    label="Resume" if state.recording.paused else "Pause",
                )
                update_recording_buttons(state)
                update_recording_indicator(
                    state,
                    "Paused" if state.recording.paused else "Recording",
                )
                update_status(
                    state,
                    "Recording paused."
                    if state.recording.paused
                    else "Recording resumed.",
                )

            def on_stop_recording(_sender: int, _app_data: None) -> None:
                if not state.recording.active:
                    update_status(state, "No active recording to stop.")
                    return
                try:
                    camera.stop_recording()
                except ValueError as exc:
                    update_status(state, f"Recording stop failed: {exc}")
                    return
                state.recording.active = False
                state.recording.paused = False
                dpg.configure_item(state.recording.pause_button_tag, label="Pause")
                update_recording_buttons(state)
                update_recording_indicator(state, "Idle")
                update_status(state, "Recording stopped.")
                state.recording.current_recording_path = None
                refresh_recordings_list(state, on_image_loaded)

            with dpg.theme() as theme_start:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(
                        dpg.mvThemeCol_Button, (0, 140, 0), category=dpg.mvThemeCat_Core
                    )
            with dpg.theme() as theme_stop:
                with dpg.theme_component(dpg.mvButton):
                    dpg.add_theme_color(
                        dpg.mvThemeCol_Button, (140, 0, 0), category=dpg.mvThemeCat_Core
                    )

            dpg.add_button(
                label="Start",
                callback=on_start_recording,
                tag=state.recording.start_button_tag,
                width=200,
                height=50,
            )
            dpg.bind_item_theme(dpg.last_item(), theme_start)
            dpg.add_button(
                label="Pause",
                tag=state.recording.pause_button_tag,
                callback=on_pause_recording,
                width=200,
                height=50,
            )
            dpg.add_button(
                label="Stop",
                callback=on_stop_recording,
                tag=state.recording.stop_button_tag,
                width=200,
                height=50,
            )
            dpg.bind_item_theme(dpg.last_item(), theme_stop)
            update_recording_buttons(state)
