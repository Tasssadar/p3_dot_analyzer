from __future__ import annotations

import dearpygui.dearpygui as dpg  # type: ignore
from p3_viewer import ColormapID  # type: ignore

from ..analysis import run_analysis
from ..camera import RENDER_HEIGHT, RENDER_WIDTH, Camera, CamFrame
from ..state import AppState
from ..named_areas import update_areas_list
from ..render import render
from ..services.analysis_service import run_batch_analysis
from ..settings_io import schedule_settings_save
from ..ui_helpers import update_status, render_frame
from .analysis_panel import (
    build_analysis_controls,
    build_percentile_table,
    show_batch_results_chart,
    update_percentile_table,
)
from .areas_panel import build_named_areas_controls
from .events import create_mouse_handlers, make_on_image_loaded_callback
from .recording_panel import (
    build_recording_tab,
    open_selected_recording,
    refresh_recordings_list,
    render_recording_frame,
    update_recording_frame_text,
)


def build_ui(app_state: AppState, camera: Camera) -> None:
    """Create Dear PyGui windows and widgets."""

    def refresh_areas_list(state: AppState) -> None:
        update_areas_list(state, on_areas_changed)

    def on_areas_changed(state: AppState) -> None:
        run_analysis(state, refresh_areas_list)

    on_image_loaded = make_on_image_loaded_callback(on_areas_changed)

    def on_mode_button_clicked(
        _sender: int, _app_data: None, user_data: AppState
    ) -> None:
        """Toggle between view mode and create_area mode."""
        if user_data.areas.interaction_mode == "view":
            user_data.areas.interaction_mode = "create_area"
            dpg.configure_item(
                user_data.areas.mode_button_tag, label="Creating... (click to cancel)"
            )
            update_status(
                user_data, "Area creation mode: drag on image to create a new area"
            )
        else:
            user_data.areas.interaction_mode = "view"
            user_data.areas.drag_start = None
            dpg.configure_item(user_data.areas.mode_button_tag, label="Create Area")
            update_status(user_data, "View mode: click on image to select a base point")
            # Remove preview rectangle if exists
            if dpg.does_item_exist(user_data.areas.preview_rect_tag):
                dpg.delete_item(user_data.areas.preview_rect_tag)

    def on_analysis_toggle(_sender: int, app_data: bool) -> None:
        """Handle analysis mode checkbox toggle."""
        app_state.analysis.enabled = app_data
        schedule_settings_save(app_state)
        if app_data:
            update_status(app_state, "Analysis mode enabled - detecting marks...")
            on_areas_changed(app_state)
            if app_state.analysis.base_x is None or app_state.analysis.base_y is None:
                update_status(
                    app_state,
                    "Analysis mode enabled - click on image to select a base point",
                )
            else:
                mark_count = sum(app_state.analysis.area_mark_counts.values())
                update_status(
                    app_state,
                    f"Analysis: found marks, {mark_count} in named areas",
                )
        else:
            update_status(app_state, "Analysis mode disabled")
            on_areas_changed(app_state)  # This will clear overlays

    def on_tolerance_change(_sender: int, app_data: int) -> None:
        """Handle tolerance input change."""
        app_state.analysis.color_tolerance = max(1, min(100, int(app_data)))
        schedule_settings_save(app_state)
        on_areas_changed(app_state)

    def on_min_area_change(_sender: int, app_data: int) -> None:
        """Handle min area input change."""
        app_state.analysis.min_area = max(10, min(5000, int(app_data)))
        schedule_settings_save(app_state)
        on_areas_changed(app_state)

    def on_max_area_change(_sender: int, app_data: int) -> None:
        """Handle max area input change."""
        app_state.analysis.max_area = max(10, min(5000, int(app_data)))
        schedule_settings_save(app_state)
        on_areas_changed(app_state)

    def on_min_circularity_change(_sender: int, app_data: float) -> None:
        """Handle min circularity input change."""
        app_state.analysis.min_circularity = max(0.0, min(1.0, float(app_data)))
        schedule_settings_save(app_state)
        on_areas_changed(app_state)

    def on_sampling_rate_change(_sender: int, app_data: int) -> None:
        """Handle sampling rate input change."""
        app_state.analysis.batch_sampling_rate = max(1, min(100, app_data))
        schedule_settings_save(app_state)

    def normalize_render_range() -> None:
        if app_state.render.temp_max <= app_state.render.temp_min:
            app_state.render.temp_max = app_state.render.temp_min + 0.1
            if dpg.does_item_exist(app_state.render.temp_max_input_tag):
                dpg.set_value(
                    app_state.render.temp_max_input_tag, app_state.render.temp_max
                )

    def rerender_current_frame() -> None:
        if app_state.render.current_frame is None:
            return
        config = app_state.build_render_config()
        img = render(
            config,
            app_state.render.current_frame.raw_thermal,
            RENDER_WIDTH,
            RENDER_HEIGHT,
        )
        app_state.render.current_frame = CamFrame(
            width=RENDER_WIDTH,
            height=RENDER_HEIGHT,
            img=img,
            raw_thermal=app_state.render.current_frame.raw_thermal,
            ts=app_state.render.current_frame.ts,
        )
        render_frame(
            app_state,
            app_state.render.current_frame,
            texture_tag=app_state.ui.texture_tag,
            draw_tag=app_state.ui.image_draw_tag,
            on_image_loaded=on_image_loaded,
        )

    def apply_render_config() -> None:
        config = app_state.build_render_config()
        camera.set_render_config(config)
        if (
            app_state.recording.reader is not None
            and app_state.ui.active_tab == "analysis_tab"
        ):
            render_recording_frame(
                app_state,
                app_state.recording.frame_index,
                on_image_loaded,
            )
        else:
            rerender_current_frame()

    def on_render_temp_min_change(_sender: int, app_data: float) -> None:
        app_state.render.temp_min = float(app_data)
        normalize_render_range()
        schedule_settings_save(app_state)
        apply_render_config()
        if app_state.analysis.enabled:
            on_areas_changed(app_state)

    def on_render_temp_max_change(_sender: int, app_data: float) -> None:
        app_state.render.temp_max = float(app_data)
        normalize_render_range()
        schedule_settings_save(app_state)
        apply_render_config()
        if app_state.analysis.enabled:
            on_areas_changed(app_state)

    def on_render_colormap_change(_sender: int, app_data: str) -> None:
        mapping = {colormap.name: colormap for colormap in ColormapID}
        if app_data in mapping:
            app_state.render.colormap = mapping[app_data]
            schedule_settings_save(app_state)
            apply_render_config()
            if app_state.analysis.enabled:
                on_areas_changed(app_state)

    def on_render_emissivity_change(_sender: int, app_data: float) -> None:
        app_state.render.emissivity = max(0.0, min(1.0, float(app_data)))
        schedule_settings_save(app_state)

    def on_render_reflected_temp_change(_sender: int, app_data: float) -> None:
        app_state.render.reflected_temp = max(-100.0, min(1000.0, float(app_data)))
        schedule_settings_save(app_state)

    def on_recording_frame_change(_sender: int, app_data: int) -> None:
        render_recording_frame(app_state, int(app_data), on_image_loaded)
        schedule_settings_save(app_state)

    def on_batch_analyze_clicked(_sender: int, _app_data: None) -> None:
        """Handle batch analysis button click."""
        # Validate prerequisites
        if app_state.analysis.base_x is None or app_state.analysis.base_y is None:
            update_status(
                app_state, "Please select a base point first (click on image)"
            )
            return

        if not app_state.areas.named_areas:
            update_status(app_state, "Please create at least one named area first")
            return

        # Disable button during analysis
        dpg.configure_item(app_state.analysis.batch_analyze_button_tag, enabled=False)
        dpg.configure_item(
            app_state.analysis.batch_analyze_button_tag, label="Analyzing..."
        )

        def progress_callback(current: int, total: int) -> None:
            update_status(app_state, f"Batch analysis: {current}/{total} images...")

        # Run batch analysis
        run_batch_analysis(app_state, progress_callback=progress_callback)

        # Re-enable button
        dpg.configure_item(app_state.analysis.batch_analyze_button_tag, enabled=True)
        dpg.configure_item(
            app_state.analysis.batch_analyze_button_tag, label="Analyze Recording"
        )

        if app_state.analysis.batch_result is not None:
            update_status(
                app_state,
                f"Batch analysis complete: {len(app_state.analysis.batch_result.timestamps)} samples",
            )
            show_batch_results_chart(app_state)
            update_percentile_table(app_state)
        else:
            update_status(app_state, "Batch analysis failed")

    if app_state.recording.selected_theme is None:
        with dpg.theme() as theme:
            with dpg.theme_component(dpg.mvSelectable):
                dpg.add_theme_color(dpg.mvThemeCol_Header, (60, 120, 200, 255))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (80, 140, 220, 255))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (50, 110, 190, 255))
        app_state.recording.selected_theme = theme

    with dpg.window(label="Image Viewer", tag="main_window", width=1300, height=760):
        dpg.add_text("", tag=app_state.ui.status_text_tag)

        with dpg.group(horizontal=True):
            # Left side: recordings list (always visible)
            with dpg.group():
                dpg.add_text("Recordings")
                with dpg.child_window(
                    tag=app_state.recording.recordings_list_tag,
                    width=360,
                    height=640,
                    border=True,
                ):
                    dpg.add_text("No recordings found")

            # Right side: tabs
            with dpg.group():
                dpg.add_separator()
                dpg.add_text("", tag=app_state.ui.timestamp_text_tag)

                def on_tab_change(_sender: int, app_data: int, _user_data: str) -> None:
                    tab_key = dpg.get_item_user_data(app_data)
                    if tab_key in ("recording_tab", "analysis_tab"):
                        app_state.ui.active_tab = tab_key
                        schedule_settings_save(app_state)

                with dpg.tab_bar(tag="tab_bar", callback=on_tab_change):
                    with dpg.tab(
                        label="Recording",
                        tag="recording_tab",
                        user_data="recording_tab",
                    ):
                        build_recording_tab(app_state, camera, on_image_loaded)

                    with dpg.tab(
                        label="Analysis",
                        tag="analysis_tab",
                        user_data="analysis_tab",
                    ):
                        with dpg.group(horizontal=True):
                            # Left side: image area
                            with dpg.group():
                                dpg.add_text("Image")
                                with dpg.drawlist(
                                    width=RENDER_WIDTH,
                                    height=RENDER_HEIGHT,
                                    tag=app_state.ui.image_drawlist_tag,
                                ):
                                    dpg.draw_image(
                                        app_state.ui.texture_tag,
                                        pmin=(0, 0),
                                        pmax=(1, 1),  # updated on render
                                        tag=app_state.ui.image_draw_tag,
                                    )
                                dpg.add_text(
                                    "Temp: --",
                                    tag=app_state.ui.hover_temp_text_tag,
                                )
                                dpg.add_separator()
                                dpg.add_text("Render Config")
                                with dpg.group(horizontal=True):
                                    dpg.add_input_float(
                                        label="Temp Min (C)",
                                        default_value=app_state.render.temp_min,
                                        callback=on_render_temp_min_change,
                                        tag=app_state.render.temp_min_input_tag,
                                        width=120,
                                        format="%.2f",
                                    )
                                    dpg.add_input_float(
                                        label="Temp Max (C)",
                                        default_value=app_state.render.temp_max,
                                        callback=on_render_temp_max_change,
                                        tag=app_state.render.temp_max_input_tag,
                                        width=120,
                                        format="%.2f",
                                    )
                                    # We only work with WHITEHOT
                                    # dpg.add_combo(
                                    #    label="Colormap",
                                    #    items=[
                                    #        colormap.name for colormap in ColormapID
                                    #    ],
                                    #    default_value=app_state.render.colormap.name,
                                    #    callback=on_render_colormap_change,
                                    #    tag=app_state.render.colormap_combo_tag,
                                    #    width=160,
                                    # )
                                with dpg.group(horizontal=True):
                                    dpg.add_input_float(
                                        label="Emissivity",
                                        default_value=app_state.render.emissivity,
                                        callback=on_render_emissivity_change,
                                        tag=app_state.render.emissivity_input_tag,
                                        width=120,
                                        format="%.3f",
                                    )
                                    dpg.add_input_float(
                                        label="Reflected (ambient) Temp (C)",
                                        default_value=app_state.render.reflected_temp,
                                        callback=on_render_reflected_temp_change,
                                        tag=app_state.render.reflected_temp_input_tag,
                                        width=140,
                                        format="%.2f",
                                    )

                            # Right side: controls
                            with dpg.group():
                                dpg.add_separator()
                                dpg.add_text("Playback")
                                dpg.add_slider_int(
                                    label="Frame",
                                    tag=app_state.recording.slider_tag,
                                    default_value=app_state.recording.frame_index,
                                    min_value=0,
                                    max_value=max(
                                        0, app_state.recording.frame_count - 1
                                    ),
                                    callback=on_recording_frame_change,
                                    width=220,
                                    enabled=app_state.recording.reader is not None,
                                )
                                dpg.add_text(
                                    "No recording loaded",
                                    tag=app_state.recording.frame_text_tag,
                                )

                                build_named_areas_controls(
                                    app_state, on_mode_button_clicked
                                )
                                build_analysis_controls(
                                    app_state,
                                    on_analysis_toggle,
                                    on_tolerance_change,
                                    on_min_area_change,
                                    on_max_area_change,
                                    on_min_circularity_change,
                                    on_sampling_rate_change,
                                    on_batch_analyze_clicked,
                                )
                        dpg.add_separator()
                        dpg.add_text(
                            "Percentile Stats (90% == 90% of dots still remain unfrozen)"
                        )
                        build_percentile_table(app_state)

                dpg.set_value("tab_bar", app_state.ui.active_tab)

    update_recording_frame_text(app_state)
    refresh_recordings_list(app_state, on_image_loaded)
    refresh_areas_list(app_state)
    if app_state.recording.selected_recording_path is not None:
        if app_state.recording.selected_recording_path.exists():
            open_selected_recording(app_state, on_image_loaded)
        else:
            app_state.recording.selected_recording_path = None
            app_state.recording.frame_index = 0

    handlers = create_mouse_handlers(app_state, on_areas_changed)
    # Global mouse handlers for color picking and area creation
    with dpg.handler_registry():
        dpg.add_mouse_click_handler(callback=handlers.on_mouse_click)
        dpg.add_mouse_move_handler(callback=handlers.on_mouse_move)
        dpg.add_mouse_down_handler(
            button=dpg.mvMouseButton_Left, callback=handlers.on_mouse_down
        )
        dpg.add_mouse_drag_handler(
            button=dpg.mvMouseButton_Left, callback=handlers.on_mouse_drag
        )
        dpg.add_mouse_release_handler(
            button=dpg.mvMouseButton_Left, callback=handlers.on_mouse_release
        )
