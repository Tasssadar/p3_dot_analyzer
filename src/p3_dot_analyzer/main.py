from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta

import dearpygui.dearpygui as dpg  # type: ignore
import os

from .analysis import run_analysis, run_batch_analysis
from .models import AppState
from .named_areas import (
    redraw_area_overlays,
    show_area_name_popup,
    update_areas_list,
)
from .settings_io import (
    apply_settings_to_state,
    get_settings_path,
    load_settings,
    schedule_settings_save,
)
from .ui_helpers import (
    screen_to_image_coords,
    sample_color_at,
    update_color_display,
    update_status,
    render_frame,
)
from .camera import (
    RENDER_HEIGHT,
    RENDER_WIDTH,
    Camera,
    CamEvRecordingStats,
    CamEvVersion,
    CamEvConnectFailed,
)
import logging


def on_image_loaded_callback(state: AppState) -> None:
    """Called after image loads - redraws areas and runs analysis if enabled."""
    redraw_area_overlays(state)
    if state.analysis_mode_enabled:
        run_analysis(state)


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
        text = (
            f"{status_label} | {duration_text} | {stats.frame_count} frames | {size_text}"
        )
    dpg.set_value(state.recording_status_tag, text)


def update_recording_buttons(state: AppState) -> None:
    start_enabled = state.camera_connected and (
        not state.recording_active or state.recording_paused
    )
    pause_enabled = state.recording_active
    stop_enabled = state.recording_active
    dpg.configure_item(state.recording_start_button_tag, enabled=start_enabled)
    dpg.configure_item(state.recording_pause_button_tag, enabled=pause_enabled)
    dpg.configure_item(state.recording_stop_button_tag, enabled=stop_enabled)


def build_ui(app_state: AppState, camera: Camera) -> None:
    """Create Dear PyGui windows and widgets."""

    def on_mode_button_clicked(
        sender: int, app_data: None, user_data: AppState
    ) -> None:
        """Toggle between view mode and create_area mode."""
        if user_data.interaction_mode == "view":
            user_data.interaction_mode = "create_area"
            dpg.configure_item(
                user_data.mode_button_tag, label="Creating... (click to cancel)"
            )
            update_status(
                user_data, "Area creation mode: drag on image to create a new area"
            )
        else:
            user_data.interaction_mode = "view"
            user_data.drag_start = None
            dpg.configure_item(user_data.mode_button_tag, label="Create Area")
            update_status(user_data, "View mode: click on image to pick a color")
            # Remove preview rectangle if exists
            if dpg.does_item_exist(user_data.preview_rect_tag):
                dpg.delete_item(user_data.preview_rect_tag)

    def on_mouse_click(sender: int, app_data: None) -> None:
        # Global mouse click handler for color picking and area creation
        if not dpg.is_item_hovered(app_state.image_drawlist_tag):
            return

        mouse_x, mouse_y = dpg.get_mouse_pos(local=False)

        if app_state.interaction_mode == "view":
            # Color picker mode - sample color at click position
            img_coords = screen_to_image_coords(app_state, mouse_x, mouse_y)
            if img_coords is not None:
                color = sample_color_at(app_state, img_coords[0], img_coords[1])
                if color is not None:
                    app_state.selected_color = color
                    update_color_display(app_state)
                    schedule_settings_save(app_state)
                    update_status(
                        app_state,
                        f"Selected color at ({img_coords[0]}, {img_coords[1]}): RGB{color}",
                    )
                    # Run analysis if analysis mode is enabled
                    if app_state.analysis_mode_enabled:
                        run_analysis(app_state)

    def on_mouse_down(sender: int, app_data: None) -> None:
        """Handle mouse down for starting area creation drag."""
        if app_state.interaction_mode != "create_area":
            return
        if not dpg.is_item_hovered(app_state.image_drawlist_tag):
            return
        if app_state.drag_start is not None:
            return

        mouse_x, mouse_y = dpg.get_mouse_pos(local=False)
        local_coords = screen_to_image_coords(app_state, mouse_x, mouse_y)
        app_state.drag_start = local_coords
        update_status(
            app_state, f"Drag started at ({local_coords[0]:.0f}, {local_coords[1]:.0f})"
        )

    def on_mouse_drag(sender: int, app_data: tuple[float, float, float]) -> None:
        """Handle mouse drag for preview rectangle."""
        if app_state.interaction_mode != "create_area":
            return
        if app_state.drag_start is None:
            return

        mouse_x, mouse_y = dpg.get_mouse_pos(local=False)
        local_coords = screen_to_image_coords(app_state, mouse_x, mouse_y)

        # Calculate rectangle bounds
        x1, y1 = app_state.drag_start
        x2, y2 = local_coords

        # Ensure proper min/max for rectangle
        min_x, max_x = min(x1, x2), max(x1, x2)
        min_y, max_y = min(y1, y2), max(y1, y2)

        # Update or create preview rectangle
        if dpg.does_item_exist(app_state.preview_rect_tag):
            dpg.configure_item(
                app_state.preview_rect_tag,
                pmin=(min_x, min_y),
                pmax=(max_x, max_y),
            )
        else:
            dpg.draw_rectangle(
                pmin=(min_x, min_y),
                pmax=(max_x, max_y),
                color=(0, 255, 0, 255),
                fill=(0, 255, 0, 50),
                thickness=2,
                tag=app_state.preview_rect_tag,
                parent=app_state.image_drawlist_tag,
            )

    def on_mouse_release(sender: int, app_data: None) -> None:
        """Handle mouse release for finalizing area creation."""
        if app_state.interaction_mode != "create_area":
            return
        if app_state.drag_start is None:
            return

        mouse_x, mouse_y = dpg.get_mouse_pos(local=False)
        local_coords = screen_to_image_coords(app_state, mouse_x, mouse_y)

        # Calculate rectangle bounds
        x1, y1 = app_state.drag_start
        x2, y2 = local_coords

        # Ensure proper min/max for rectangle
        min_x, max_x = min(x1, x2), max(x1, x2)
        min_y, max_y = min(y1, y2), max(y1, y2)

        width = max_x - min_x
        height = max_y - min_y

        # Only create area if it has some size
        if width < 5 or height < 5:
            app_state.drag_start = None
            if dpg.does_item_exist(app_state.preview_rect_tag):
                dpg.delete_item(app_state.preview_rect_tag)
            update_status(app_state, "Area too small, cancelled")
            return

        # Store the pending area bounds for the popup
        pending_area_bounds = (int(min_x), int(min_y), int(width), int(height))

        # Remove preview rectangle
        if dpg.does_item_exist(app_state.preview_rect_tag):
            dpg.delete_item(app_state.preview_rect_tag)

        # Show name input popup
        show_area_name_popup(app_state, pending_area_bounds)

        app_state.drag_start = None

    def on_analysis_toggle(sender: int, app_data: bool) -> None:
        """Handle analysis mode checkbox toggle."""
        app_state.analysis_mode_enabled = app_data
        schedule_settings_save(app_state)
        if app_data:
            update_status(app_state, "Analysis mode enabled - detecting marks...")
            run_analysis(app_state)
            if app_state.selected_color is None:
                update_status(
                    app_state,
                    "Analysis mode enabled - click on image to select a color",
                )
            else:
                mark_count = sum(app_state.area_mark_counts.values())
                update_status(
                    app_state,
                    f"Analysis: found marks, {mark_count} in named areas",
                )
        else:
            update_status(app_state, "Analysis mode disabled")
            run_analysis(app_state)  # This will clear overlays

    def on_tolerance_change(sender: int, app_data: int) -> None:
        """Handle tolerance input change."""
        app_state.color_tolerance = max(1, min(100, int(app_data)))
        schedule_settings_save(app_state)
        run_analysis(app_state)

    def on_min_area_change(sender: int, app_data: int) -> None:
        """Handle min area input change."""
        app_state.min_area = max(10, min(5000, int(app_data)))
        schedule_settings_save(app_state)
        run_analysis(app_state)

    def on_min_circularity_change(sender: int, app_data: float) -> None:
        """Handle min circularity input change."""
        app_state.min_circularity = max(0.0, min(1.0, float(app_data)))
        schedule_settings_save(app_state)
        run_analysis(app_state)

    def on_sampling_rate_change(sender: int, app_data: int) -> None:
        """Handle sampling rate input change."""
        app_state.batch_sampling_rate = max(1, min(100, app_data))
        schedule_settings_save(app_state)

    def on_recording_frame_period_change(sender: int, app_data: int) -> None:
        """Handle recording frame period input change."""
        app_state.recording_frame_period_ms = max(1, min(10000, int(app_data)))

    def on_batch_analyze_clicked(sender: int, app_data: None) -> None:
        """Handle batch analysis button click."""
        # Validate prerequisites
        if app_state.selected_color is None:
            update_status(app_state, "Please select a color first (click on image)")
            return

        if not app_state.named_areas:
            update_status(app_state, "Please create at least one named area first")
            return

        # Disable button during analysis
        dpg.configure_item(app_state.batch_analyze_button_tag, enabled=False)
        dpg.configure_item(app_state.batch_analyze_button_tag, label="Analyzing...")

        def progress_callback(current: int, total: int) -> None:
            update_status(app_state, f"Batch analysis: {current}/{total} images...")

        # Run batch analysis
        run_batch_analysis(app_state, progress_callback=progress_callback)

        # Re-enable button
        dpg.configure_item(app_state.batch_analyze_button_tag, enabled=True)
        dpg.configure_item(
            app_state.batch_analyze_button_tag, label="Analyze Whole Batch"
        )

        if app_state.batch_result is not None:
            update_status(
                app_state,
                f"Batch analysis complete: {len(app_state.batch_result.timestamps)} samples",
            )
            show_batch_results_chart(app_state)
        else:
            update_status(app_state, "Batch analysis failed")

    def get_recordings_dir() -> Path:
        if app_state.recordings_dir is None:
            app_state.recordings_dir = Path(os.getcwd()) / "recordings"
        return app_state.recordings_dir

    def list_recordings() -> list[Path]:
        recordings_dir = get_recordings_dir()
        if not recordings_dir.exists():
            return []
        return sorted(recordings_dir.glob("*.mp4"), key=lambda p: p.name.lower())

    def refresh_recordings_list() -> None:
        if not dpg.does_item_exist(app_state.recordings_list_tag):
            return
        dpg.delete_item(app_state.recordings_list_tag, children_only=True)
        recordings = list_recordings()
        if not recordings:
            dpg.add_text("No recordings found", parent=app_state.recordings_list_tag)
            return
        for rec_path in recordings:
            is_selected = app_state.selected_recording_path == rec_path

            def on_select(sender: int, app_data: bool, user_data: Path) -> None:
                if not app_data:
                    return
                app_state.selected_recording_path = user_data
                update_status(app_state, f"Selected recording: {user_data.name}")
                # TODO: Hook up playback for selected recording.
                refresh_recordings_list()

            with dpg.group(horizontal=True, parent=app_state.recordings_list_tag):
                dpg.add_selectable(
                    label=rec_path.name,
                    default_value=is_selected,
                    callback=on_select,
                    user_data=rec_path,
                    width=210,
                )

                def on_rename_clicked(
                    sender: int, app_data: None, user_data: Path
                ) -> None:
                    if (
                        app_state.recording_active
                        and app_state.current_recording_path == user_data
                    ):
                        update_status(app_state, "Cannot rename the active recording.")
                        return
                    show_rename_modal(user_data)

                def on_delete_clicked(
                    sender: int, app_data: None, user_data: Path
                ) -> None:
                    if (
                        app_state.recording_active
                        and app_state.current_recording_path == user_data
                    ):
                        update_status(app_state, "Cannot delete the active recording.")
                        return
                    try:
                        if user_data.exists():
                            user_data.unlink()
                        if app_state.selected_recording_path == user_data:
                            app_state.selected_recording_path = None
                        update_status(app_state, f"Deleted recording: {user_data.name}")
                    except OSError as exc:
                        update_status(
                            app_state,
                            f"Failed to delete recording: {user_data.name} ({exc})",
                        )
                    refresh_recordings_list()

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

    def show_rename_modal(target_path: Path) -> None:
        if dpg.does_item_exist(app_state.rename_modal_tag):
            dpg.delete_item(app_state.rename_modal_tag)

        def on_confirm(sender: int, app_data: None) -> None:
            new_name = dpg.get_value(app_state.rename_input_tag).strip()
            if not new_name:
                update_status(app_state, "Recording name cannot be empty.")
                return
            if any(sep in new_name for sep in ("/", "\\")):
                update_status(
                    app_state, "Recording name cannot contain path separators."
                )
                return
            recordings_dir = get_recordings_dir()
            new_path = recordings_dir / f"{new_name}{target_path.suffix}"
            if new_path.exists():
                update_status(app_state, "A recording with that name already exists.")
                return
            try:
                target_path.rename(new_path)
                if app_state.selected_recording_path == target_path:
                    app_state.selected_recording_path = new_path
                update_status(app_state, f"Renamed recording to: {new_path.name}")
            except OSError as exc:
                update_status(
                    app_state,
                    f"Failed to rename recording: {target_path.name} ({exc})",
                )
            dpg.delete_item(app_state.rename_modal_tag)
            refresh_recordings_list()

        def on_cancel(sender: int, app_data: None) -> None:
            dpg.delete_item(app_state.rename_modal_tag)

        with dpg.window(
            label="Rename Recording",
            tag=app_state.rename_modal_tag,
            modal=True,
            no_close=True,
            pos=(400, 300),
            width=320,
            height=140,
        ):
            dpg.add_text(f"Current: {target_path.name}")
            dpg.add_input_text(
                label="New name",
                tag=app_state.rename_input_tag,
                default_value=target_path.stem,
                width=220,
            )
            with dpg.group(horizontal=True):
                dpg.add_button(label="Rename", callback=on_confirm)
                dpg.add_button(label="Cancel", callback=on_cancel)

    def show_batch_results_chart(state: AppState) -> None:
        """Show or update the batch results chart window."""
        if state.batch_result is None:
            return

        # Delete existing chart window if it exists
        if dpg.does_item_exist(state.batch_chart_window_tag):
            dpg.delete_item(state.batch_chart_window_tag)

        # Colors for different areas (matching named_areas.py)
        colors = [
            (255, 0, 0),  # Red
            (0, 0, 255),  # Blue
            (255, 165, 0),  # Orange
            (128, 0, 128),  # Purple
            (0, 128, 128),  # Teal
        ]

        with dpg.window(
            label="Batch Analysis Results",
            tag=state.batch_chart_window_tag,
            width=800,
            height=500,
            pos=(200, 100),
        ):
            # Create plot
            with dpg.plot(
                label="Marks Over Time",
                height=-1,
                width=-1,
                tag=state.batch_plot_tag,
            ):
                # Add legend
                dpg.add_plot_legend()

                # Add axes
                dpg.add_plot_axis(dpg.mvXAxis, label="Time (seconds)", tag="x_axis")
                dpg.add_plot_axis(dpg.mvYAxis, label="Number of Marks", tag="y_axis")

                # Add line series for each named area
                timestamps = state.batch_result.timestamps
                for i, area in enumerate(state.named_areas):
                    area_name = area.name
                    if area_name in state.batch_result.area_counts:
                        counts = state.batch_result.area_counts[area_name]
                        color = colors[i % len(colors)]
                        dpg.add_line_series(
                            timestamps,
                            counts,
                            label=area_name,
                            parent="y_axis",
                        )
                        # Set series color
                        dpg.bind_item_theme(
                            dpg.last_item(),
                            create_line_theme(color),
                        )

    def create_line_theme(color: tuple[int, int, int]) -> int:
        """Create a theme for a line series with the given color."""
        with dpg.theme() as theme:
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(
                    dpg.mvPlotCol_Line,
                    (color[0], color[1], color[2], 255),
                    category=dpg.mvThemeCat_Plots,
                )
        return theme  # type: ignore

    with dpg.window(label="Image Viewer", tag="main_window", width=1300, height=760):
        dpg.add_text("", tag=app_state.status_text_tag)

        with dpg.group(horizontal=True):
            # Left side: recordings list (always visible)
            with dpg.group():
                dpg.add_text("Recordings")
                with dpg.child_window(
                    tag=app_state.recordings_list_tag,
                    width=360,
                    height=640,
                    border=True,
                ):
                    dpg.add_text("No recordings found")

            # Right side: tabs
            with dpg.group():
                dpg.add_separator()
                dpg.add_text("", tag=app_state.timestamp_text_tag)

                def on_tab_change(sender: int, app_data: str) -> None:
                    app_state.active_tab = app_data

                with dpg.tab_bar(callback=on_tab_change):
                    with dpg.tab(label="Recording", tag="recording_tab"):
                        with dpg.group(horizontal=True):
                            with dpg.group():
                                dpg.add_text("Camera")
                                with dpg.drawlist(
                                    width=800,
                                    height=600,
                                    tag=app_state.recording_drawlist_tag,
                                ):
                                    dpg.draw_image(
                                        app_state.texture_tag,
                                        pmin=(0, 0),
                                        pmax=(1, 1),  # updated on render
                                        tag=app_state.recording_draw_tag,
                                    )
                            with dpg.group():
                                dpg.add_text("Recording Controls")
                                dpg.add_separator()
                                dpg.add_text(
                                    "Idle", tag=app_state.recording_status_tag
                                )
                                dpg.add_input_int(
                                    label="Frame period (ms)",
                                    default_value=app_state.recording_frame_period_ms,
                                    min_value=1,
                                    max_value=10000,
                                    min_clamped=True,
                                    max_clamped=True,
                                    callback=on_recording_frame_period_change,
                                    tag=app_state.recording_frame_period_input_tag,
                                    width=140,
                                )

                                def on_start_recording(
                                    sender: int, app_data: None
                                ) -> None:
                                    if not app_state.camera_connected:
                                        update_status(
                                            app_state,
                                            "Camera not connected. Connect the camera first.",
                                        )
                                        return
                                    if app_state.recording_active:
                                        update_status(
                                            app_state, "Recording already in progress."
                                        )
                                        return
                                    recordings_dir = get_recordings_dir()
                                    recordings_dir.mkdir(parents=True, exist_ok=True)
                                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                    recording_path = (
                                        recordings_dir / f"recording_{timestamp}.mp4"
                                    )
                                    frame_period = timedelta(
                                        milliseconds=app_state.recording_frame_period_ms
                                    )
                                    try:
                                        camera.start_recording(
                                            recording_path, frame_period
                                        )
                                    except ValueError as exc:
                                        update_status(
                                            app_state, f"Recording start failed: {exc}"
                                        )
                                        return
                                    app_state.current_recording_path = recording_path
                                    app_state.recording_active = True
                                    app_state.recording_paused = False
                                    dpg.configure_item(
                                        app_state.recording_pause_button_tag, label="Pause"
                                    )
                                    update_recording_buttons(app_state)
                                    update_recording_indicator(app_state, "Recording")
                                    update_status(
                                        app_state,
                                        f"Recording started: {recording_path.name}",
                                    )

                                def on_pause_recording(
                                    sender: int, app_data: None
                                ) -> None:
                                    if not app_state.recording_active:
                                        update_status(
                                            app_state, "No active recording to pause."
                                        )
                                        return
                                    app_state.recording_paused = (
                                        not app_state.recording_paused
                                    )
                                    camera.pause_recording(app_state.recording_paused)
                                    dpg.configure_item(
                                        app_state.recording_pause_button_tag,
                                        label="Resume"
                                        if app_state.recording_paused
                                        else "Pause",
                                    )
                                    update_recording_buttons(app_state)
                                    update_recording_indicator(
                                        app_state,
                                        "Paused"
                                        if app_state.recording_paused
                                        else "Recording",
                                    )
                                    update_status(
                                        app_state,
                                        "Recording paused."
                                        if app_state.recording_paused
                                        else "Recording resumed.",
                                    )

                                def on_stop_recording(
                                    sender: int, app_data: None
                                ) -> None:
                                    if not app_state.recording_active:
                                        update_status(
                                            app_state, "No active recording to stop."
                                        )
                                        return
                                    try:
                                        camera.stop_recording()
                                    except ValueError as exc:
                                        update_status(
                                            app_state, f"Recording stop failed: {exc}"
                                        )
                                        return
                                    app_state.recording_active = False
                                    app_state.recording_paused = False
                                    dpg.configure_item(
                                        app_state.recording_pause_button_tag, label="Pause"
                                    )
                                    update_recording_buttons(app_state)
                                    update_recording_indicator(app_state, "Idle")
                                    update_status(
                                        app_state,
                                        "Recording stopped.",
                                    )
                                    app_state.current_recording_path = None
                                    refresh_recordings_list()

                                dpg.add_button(
                                    label="Start",
                                    callback=on_start_recording,
                                    tag=app_state.recording_start_button_tag,
                                    width=200,
                                    height=50,
                                )
                                dpg.add_button(
                                    label="Pause",
                                    tag=app_state.recording_pause_button_tag,
                                    callback=on_pause_recording,
                                    width=200,
                                    height=50,
                                )
                                dpg.add_button(
                                    label="Stop",
                                    callback=on_stop_recording,
                                    tag=app_state.recording_stop_button_tag,
                                    width=200,
                                    height=50,
                                )
                                update_recording_buttons(app_state)

                    with dpg.tab(label="Analysis", tag="analysis_tab"):
                        with dpg.group(horizontal=True):
                            # Left side: image area
                            with dpg.group():
                                dpg.add_text("Image")
                                with dpg.drawlist(
                                    width=800,
                                    height=600,
                                    tag=app_state.image_drawlist_tag,
                                ):
                                    dpg.draw_image(
                                        app_state.texture_tag,
                                        pmin=(0, 0),
                                        pmax=(1, 1),  # updated on render
                                        tag=app_state.image_draw_tag,
                                    )

                            # Right side: controls
                            with dpg.group():
                                dpg.add_separator()

                                # Color picker display
                                dpg.add_separator()
                                dpg.add_text("Selected Color:")
                                with dpg.drawlist(
                                    width=60, height=30, tag="color_swatch_drawlist"
                                ):
                                    dpg.draw_rectangle(
                                        pmin=(0, 0),
                                        pmax=(60, 30),
                                        fill=(128, 128, 128, 255),
                                        color=(200, 200, 200, 255),
                                        tag=app_state.color_swatch_tag,
                                    )
                                dpg.add_text(
                                    "No color selected", tag=app_state.color_text_tag
                                )

                                # Named areas controls
                                dpg.add_separator()
                                dpg.add_text("Named Areas:")
                                dpg.add_button(
                                    label="Create Area",
                                    callback=on_mode_button_clicked,
                                    user_data=app_state,
                                    tag=app_state.mode_button_tag,
                                )

                                dpg.add_separator()
                                dpg.add_text("Named Areas:")
                                dpg.add_text("(Click 'Create Area' then drag on image)")
                                dpg.add_separator()

                                # Areas list container
                                with dpg.child_window(
                                    tag=app_state.areas_list_tag,
                                    height=250,
                                    border=True,
                                ):
                                    dpg.add_text("No areas defined")

                                dpg.add_separator()
                                dpg.add_text("Analysis:")
                                dpg.add_checkbox(
                                    label="Enable Analysis Mode",
                                    callback=on_analysis_toggle,
                                    tag=app_state.analysis_checkbox_tag,
                                    default_value=app_state.analysis_mode_enabled,
                                )
                                dpg.add_input_int(
                                    label="Tolerance (1-100)",
                                    default_value=app_state.color_tolerance,
                                    min_value=1,
                                    max_value=100,
                                    min_clamped=True,
                                    max_clamped=True,
                                    callback=on_tolerance_change,
                                    tag=app_state.tolerance_input_tag,
                                    width=120,
                                )
                                dpg.add_input_int(
                                    label="Min Area (10-5000)",
                                    default_value=app_state.min_area,
                                    min_value=10,
                                    max_value=5000,
                                    min_clamped=True,
                                    max_clamped=True,
                                    callback=on_min_area_change,
                                    tag=app_state.min_area_input_tag,
                                    width=120,
                                )
                                dpg.add_input_float(
                                    label="Min Circularity (0-1)",
                                    default_value=app_state.min_circularity,
                                    min_value=0.0,
                                    max_value=1.0,
                                    min_clamped=True,
                                    max_clamped=True,
                                    callback=on_min_circularity_change,
                                    tag=app_state.min_circularity_input_tag,
                                    width=120,
                                    format="%.2f",
                                )

                                # Batch analysis controls
                                dpg.add_separator()
                                dpg.add_text("Batch Analysis:")
                                dpg.add_input_int(
                                    label="Sampling (1-100)",
                                    default_value=app_state.batch_sampling_rate,
                                    min_value=1,
                                    max_value=100,
                                    min_clamped=True,
                                    max_clamped=True,
                                    callback=on_sampling_rate_change,
                                    tag=app_state.batch_sampling_input_tag,
                                    width=100,
                                )
                                dpg.add_text(
                                    "(e.g., 5 = every 5th image)", color=(150, 150, 150)
                                )
                                dpg.add_button(
                                    label="Analyze Whole Batch",
                                    callback=on_batch_analyze_clicked,
                                    tag=app_state.batch_analyze_button_tag,
                                )

    refresh_recordings_list()

    # Global mouse handlers for color picking and area creation
    with dpg.handler_registry():
        dpg.add_mouse_click_handler(callback=on_mouse_click)
        dpg.add_mouse_down_handler(
            button=dpg.mvMouseButton_Left, callback=on_mouse_down
        )
        dpg.add_mouse_drag_handler(
            button=dpg.mvMouseButton_Left, callback=on_mouse_drag
        )
        dpg.add_mouse_release_handler(
            button=dpg.mvMouseButton_Left, callback=on_mouse_release
        )


def run() -> None:
    """Application entry point that sets up and runs the Dear PyGui app."""
    base_dir = Path(os.getcwd())
    settings_path = get_settings_path(base_dir)

    logging.basicConfig(level=logging.DEBUG)

    dpg.create_context()

    texture_tag = "image_texture"
    app_state = AppState(
        texture_tag=texture_tag,
        image_drawlist_tag="image_drawlist",
        image_draw_tag="image_draw",
        slider_tag="image_slider",
        filename_text_tag="filename_text",
        status_text_tag="status_text",
        settings_path=settings_path,
    )
    app_state.recordings_dir = base_dir / "recordings"

    camera = Camera()

    settings = load_settings(settings_path)
    if settings is not None:
        apply_settings_to_state(app_state, settings)

    with dpg.texture_registry():
        dpg.add_dynamic_texture(
            RENDER_WIDTH,
            RENDER_HEIGHT,
            [0] * RENDER_WIDTH * RENDER_HEIGHT * 4,
            tag=texture_tag,
        )

    build_ui(app_state, camera)
    update_color_display(app_state)
    update_areas_list(app_state)

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
                    update_status(
                        app_state, f"Camera connected: {ev.name} {ev.version}"
                    )
                    update_recording_buttons(app_state)
                case CamEvConnectFailed():
                    app_state.camera_connected = False
                    update_status(app_state, f"Connect failed: {ev.message}")
                    update_recording_buttons(app_state)
                case CamEvRecordingStats():
                    if app_state.recording_active:
                        status_label = (
                            "Paused" if app_state.recording_paused else "Recording"
                        )
                    else:
                        status_label = "Idle"
                    update_recording_indicator(app_state, status_label, ev)

            frame = camera.take_frame()
            if frame is not None:
                app_state.current_frame = frame
                render_frame(app_state, on_image_loaded=on_image_loaded_callback)

            dpg.render_dearpygui_frame()
    finally:
        camera.stop()
        dpg.destroy_context()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
