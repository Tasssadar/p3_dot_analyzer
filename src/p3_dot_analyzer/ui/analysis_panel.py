from __future__ import annotations

from collections.abc import Callable

import dearpygui.dearpygui as dpg  # type: ignore

from ..constants import AREA_COLORS_RGB
from ..state import AppState
from .recording_panel import render_recording_frame


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


def show_batch_results_chart(state: AppState) -> None:
    """Show or update the batch results chart window."""
    if state.analysis.batch_result is None:
        return

    # Delete existing chart window if it exists
    if dpg.does_item_exist(state.analysis.batch_chart_window_tag):
        dpg.delete_item(state.analysis.batch_chart_window_tag)

    with dpg.window(
        label="Batch Analysis Results",
        tag=state.analysis.batch_chart_window_tag,
        width=800,
        height=500,
        pos=(200, 100),
    ):
        # Create plot
        with dpg.plot(
            label="Marks Over Time",
            height=-1,
            width=-1,
            tag=state.analysis.batch_plot_tag,
        ):
            # Add legend
            dpg.add_plot_legend()

            # Add axes
            dpg.add_plot_axis(dpg.mvXAxis, label="Time (seconds)", tag="x_axis")
            dpg.add_plot_axis(dpg.mvYAxis, label="Number of Marks", tag="y_axis")

            # Add line series for each named area
            timestamps = state.analysis.batch_result.timestamps
            for i, area in enumerate(state.areas.named_areas):
                area_name = area.name
                if area_name in state.analysis.batch_result.area_counts:
                    counts = state.analysis.batch_result.area_counts[area_name]
                    color = AREA_COLORS_RGB[i % len(AREA_COLORS_RGB)]
                    dpg.add_line_series(
                        timestamps,
                        counts,
                        label=area_name,
                        parent="y_axis",
                    )
                    # Set series color
                    dpg.bind_item_theme(dpg.last_item(), create_line_theme(color))


def build_percentile_table(state: AppState) -> None:
    with dpg.child_window(
        tag=state.analysis.batch_percentile_container_tag,
        border=True,
        height=180,
        width=-1,
    ):
        dpg.add_text("Run batch analysis to see percentile stats.")


def update_percentile_table(
    state: AppState,
    on_image_loaded: Callable[[AppState], None] | None = None,
) -> None:
    if not dpg.does_item_exist(state.analysis.batch_percentile_container_tag):
        return

    dpg.delete_item(state.analysis.batch_percentile_container_tag, children_only=True)

    if state.analysis.batch_result is None:
        dpg.add_text(
            "Run batch analysis to see percentile stats.",
            parent=state.analysis.batch_percentile_container_tag,
        )
        return

    percentiles = sorted(state.analysis.batch_result.percentile_for_area.keys())
    if not percentiles:
        dpg.add_text(
            "No percentile data available.",
            parent=state.analysis.batch_percentile_container_tag,
        )
        return

    def on_view_clicked(_sender: int, _app_data: None, user_data: int) -> None:
        if state.recording.reader is None or state.recording.frame_count <= 0:
            return
        render_recording_frame(state, user_data, on_image_loaded)

    with dpg.table(
        tag=state.analysis.batch_percentile_table_tag,
        header_row=True,
        resizable=True,
        policy=dpg.mvTable_SizingStretchProp,
        borders_innerH=True,
        borders_innerV=True,
        borders_outerH=True,
        borders_outerV=True,
        parent=state.analysis.batch_percentile_container_tag,
    ):
        dpg.add_table_column(label="Area")
        for pct in percentiles:
            dpg.add_table_column(label=f"{pct}%")

        for area in state.areas.named_areas:
            area_name = area.name
            with dpg.table_row():
                dpg.add_text(area_name)
                for pct in percentiles:
                    area_map = state.analysis.batch_result.percentile_for_area.get(
                        pct, {}
                    )
                    ps = area_map.get(area_name)
                    if ps is None:
                        dpg.add_text("--")
                    else:
                        with dpg.group(horizontal=True):
                            dpg.add_text(f"{ps.timestamp:6.2f}s")
                            dpg.add_button(
                                label="View",
                                callback=on_view_clicked,
                                user_data=ps.frame_index,
                                enabled=state.recording.reader is not None
                                and state.recording.frame_count > 0,
                                width=45,
                            )
                            dpg.add_text(
                                f"{ps.base_temp_c:4.2f} °C    {ps.count_cur:2} / {ps.count_max:2} frozen"
                            )


def build_analysis_controls(
    state: AppState,
    on_analysis_toggle: Callable[[int, bool], None],
    on_tolerance_change: Callable[[int, int], None],
    on_min_area_change: Callable[[int, int], None],
    on_max_area_change: Callable[[int, int], None],
    on_min_circularity_change: Callable[[int, float], None],
    on_sampling_rate_change: Callable[[int, int], None],
    on_batch_analyze_clicked: Callable[[int, None], None],
) -> None:
    dpg.add_separator()
    dpg.add_text("Analysis:")
    dpg.add_checkbox(
        label="Enable Analysis Mode",
        callback=on_analysis_toggle,
        tag=state.analysis.checkbox_tag,
        default_value=state.analysis.enabled,
    )
    dpg.add_input_int(
        label="Tolerance (1-100)",
        default_value=state.analysis.color_tolerance,
        min_value=1,
        max_value=100,
        min_clamped=True,
        max_clamped=True,
        callback=on_tolerance_change,
        tag=state.analysis.tolerance_input_tag,
        width=120,
    )
    dpg.add_input_int(
        label="Min Area (10-5000)",
        default_value=state.analysis.min_area,
        min_value=10,
        max_value=5000,
        min_clamped=True,
        max_clamped=True,
        callback=on_min_area_change,
        tag=state.analysis.min_area_input_tag,
        width=120,
    )
    dpg.add_input_int(
        label="Max Area (10-5000)",
        default_value=state.analysis.max_area,
        min_value=10,
        max_value=5000,
        min_clamped=True,
        max_clamped=True,
        callback=on_max_area_change,
        tag=state.analysis.max_area_input_tag,
        width=120,
    )
    dpg.add_input_float(
        label="Min Circularity (0-1)",
        default_value=state.analysis.min_circularity,
        min_value=0.0,
        max_value=1.0,
        min_clamped=True,
        max_clamped=True,
        callback=on_min_circularity_change,
        tag=state.analysis.min_circularity_input_tag,
        width=120,
        format="%.2f",
    )

    # Batch analysis controls
    dpg.add_separator()
    dpg.add_spacer(height=5)

    dpg.add_text("Batch Analysis:")
    with dpg.group(horizontal=True):
        with dpg.theme() as analyze_theme:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(
                    dpg.mvThemeCol_Button, (0, 140, 0), category=dpg.mvThemeCat_Core
                )

        dpg.add_button(
            label="Analyze Recording",
            height=50,
            width=200,
            callback=on_batch_analyze_clicked,
            tag=state.analysis.batch_analyze_button_tag,
        )
        dpg.bind_item_theme(dpg.last_item(), analyze_theme)
        with dpg.group():
            dpg.add_input_int(
                label="Sampling (1-100)",
                default_value=state.analysis.batch_sampling_rate,
                min_value=1,
                max_value=100,
                min_clamped=True,
                max_clamped=True,
                callback=on_sampling_rate_change,
                tag=state.analysis.batch_sampling_input_tag,
                width=100,
            )
            dpg.add_text("(e.g., 5 = every 5th image)", color=(150, 150, 150))
