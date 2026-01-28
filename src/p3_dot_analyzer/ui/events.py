from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

import dearpygui.dearpygui as dpg  # type: ignore

from ..state import AppState
from ..named_areas import redraw_area_overlays, show_area_name_popup
from ..settings_io import schedule_settings_save
from ..ui_helpers import (
    screen_to_image_coords,
    get_temp_at,
    update_color_display,
    update_status,
)


@dataclass(slots=True)
class MouseHandlers:
    on_mouse_click: Callable[[int, None], None]
    on_mouse_move: Callable[[int, tuple[float, float]], None]
    on_mouse_down: Callable[[int, None], None]
    on_mouse_drag: Callable[[int, tuple[float, float, float]], None]
    on_mouse_release: Callable[[int, None], None]


def make_on_image_loaded_callback(
    on_analysis_update: Callable[[AppState], None],
) -> Callable[[AppState], None]:
    """Return a callback to refresh overlays and analysis after image load."""

    def on_image_loaded(state: AppState) -> None:
        redraw_area_overlays(state)
        if state.analysis.enabled:
            on_analysis_update(state)

    return on_image_loaded


def create_mouse_handlers(
    app_state: AppState, on_analysis_update: Callable[[AppState], None]
) -> MouseHandlers:
    """Create mouse handlers for temperature selection and area creation."""

    def on_mouse_click(_sender: int, _app_data: None) -> None:
        # Global mouse click handler for color picking and area creation
        if not dpg.is_item_hovered(app_state.ui.image_drawlist_tag):
            return

        mouse_x, mouse_y = dpg.get_mouse_pos(local=False)

        if app_state.areas.interaction_mode == "view":
            # Temperature picker mode - sample temp at click position
            img_coords = screen_to_image_coords(app_state, mouse_x, mouse_y)
            if img_coords is not None:
                temp = get_temp_at(app_state, img_coords[0], img_coords[1])
                if temp is not None:
                    app_state.analysis.selected_temp = temp
                    update_color_display(app_state)
                    schedule_settings_save(app_state)
                    update_status(
                        app_state,
                        f"Selected temp at ({img_coords[0]}, {img_coords[1]}): {temp:.2f} C",
                    )
                    # Run analysis if analysis mode is enabled
                    on_analysis_update(app_state)

    def on_mouse_move(_sender: int, _app_data: tuple[float, float]) -> None:
        if not dpg.is_item_hovered(app_state.ui.image_drawlist_tag):
            dpg.set_value(app_state.ui.hover_temp_text_tag, "Temp: --")
            return

        mouse_x, mouse_y = dpg.get_mouse_pos(local=False)
        img_x, img_y = screen_to_image_coords(app_state, mouse_x, mouse_y)
        temp = get_temp_at(app_state, img_x, img_y)
        if temp is None:
            dpg.set_value(app_state.ui.hover_temp_text_tag, "Temp: --")
        else:
            dpg.set_value(app_state.ui.hover_temp_text_tag, f"Temp: {temp:.2f} C")

    def on_mouse_down(_sender: int, _app_data: None) -> None:
        """Handle mouse down for starting area creation drag."""
        if app_state.areas.interaction_mode != "create_area":
            return
        if not dpg.is_item_hovered(app_state.ui.image_drawlist_tag):
            return
        if app_state.areas.drag_start is not None:
            return

        mouse_x, mouse_y = dpg.get_mouse_pos(local=False)
        local_coords = screen_to_image_coords(app_state, mouse_x, mouse_y)
        app_state.areas.drag_start = local_coords
        update_status(
            app_state, f"Drag started at ({local_coords[0]:.0f}, {local_coords[1]:.0f})"
        )

    def on_mouse_drag(_sender: int, _app_data: tuple[float, float, float]) -> None:
        """Handle mouse drag for preview rectangle."""
        if app_state.areas.interaction_mode != "create_area":
            return
        if app_state.areas.drag_start is None:
            return

        mouse_x, mouse_y = dpg.get_mouse_pos(local=False)
        local_coords = screen_to_image_coords(app_state, mouse_x, mouse_y)

        # Calculate rectangle bounds
        x1, y1 = app_state.areas.drag_start
        x2, y2 = local_coords

        # Ensure proper min/max for rectangle
        min_x, max_x = min(x1, x2), max(x1, x2)
        min_y, max_y = min(y1, y2), max(y1, y2)

        # Update or create preview rectangle
        if dpg.does_item_exist(app_state.areas.preview_rect_tag):
            dpg.configure_item(
                app_state.areas.preview_rect_tag,
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
                tag=app_state.areas.preview_rect_tag,
                parent=app_state.ui.image_drawlist_tag,
            )

    def on_mouse_release(_sender: int, _app_data: None) -> None:
        """Handle mouse release for finalizing area creation."""
        if app_state.areas.interaction_mode != "create_area":
            return
        if app_state.areas.drag_start is None:
            return

        mouse_x, mouse_y = dpg.get_mouse_pos(local=False)
        local_coords = screen_to_image_coords(app_state, mouse_x, mouse_y)

        # Calculate rectangle bounds
        x1, y1 = app_state.areas.drag_start
        x2, y2 = local_coords

        # Ensure proper min/max for rectangle
        min_x, max_x = min(x1, x2), max(x1, x2)
        min_y, max_y = min(y1, y2), max(y1, y2)

        width = max_x - min_x
        height = max_y - min_y

        # Only create area if it has some size
        if width < 5 or height < 5:
            app_state.areas.drag_start = None
            if dpg.does_item_exist(app_state.areas.preview_rect_tag):
                dpg.delete_item(app_state.areas.preview_rect_tag)
            update_status(app_state, "Area too small, cancelled")
            return

        # Store the pending area bounds for the popup
        pending_area_bounds = (int(min_x), int(min_y), int(width), int(height))

        # Remove preview rectangle
        if dpg.does_item_exist(app_state.areas.preview_rect_tag):
            dpg.delete_item(app_state.areas.preview_rect_tag)

        # Show name input popup
        show_area_name_popup(app_state, pending_area_bounds, on_analysis_update)

        app_state.areas.drag_start = None

    return MouseHandlers(
        on_mouse_click=on_mouse_click,
        on_mouse_move=on_mouse_move,
        on_mouse_down=on_mouse_down,
        on_mouse_drag=on_mouse_drag,
        on_mouse_release=on_mouse_release,
    )
