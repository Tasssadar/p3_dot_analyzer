from __future__ import annotations

from typing import Callable
import dearpygui.dearpygui as dpg  # type: ignore

from .state import AppState
from .constants import AREA_COLORS_RGBA, AREA_FILL_ALPHA
from .services.areas_service import create_named_area, delete_named_area
from .settings_io import schedule_settings_save
from .ui_helpers import update_status


def redraw_area_overlays(app_state: AppState) -> None:
    """Redraw all named area rectangles on the image drawlist."""
    # Remove existing overlay rectangles
    for tag in app_state.areas.area_overlay_tags:
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)
    app_state.areas.area_overlay_tags.clear()

    # Draw each named area
    for i, area in enumerate(app_state.areas.named_areas):
        color = AREA_COLORS_RGBA[i % len(AREA_COLORS_RGBA)]
        fill_color = (color[0], color[1], color[2], AREA_FILL_ALPHA)

        # Draw rectangle
        rect_tag = f"area_rect_{i}"
        dpg.draw_rectangle(
            pmin=(area.x, area.y),
            pmax=(area.x + area.width, area.y + area.height),
            color=color,
            fill=fill_color,
            thickness=2,
            tag=rect_tag,
            parent=app_state.ui.image_drawlist_tag,
        )
        app_state.areas.area_overlay_tags.append(rect_tag)

        # Draw label
        label_tag = f"area_label_{i}"
        dpg.draw_text(
            pos=(area.x + 2, area.y + 2),
            text=area.name,
            color=(255, 255, 255, 255),
            size=14,
            tag=label_tag,
            parent=app_state.ui.image_drawlist_tag,
        )
        app_state.areas.area_overlay_tags.append(label_tag)


def update_areas_list(
    app_state: AppState,
    on_areas_changed: Callable[[AppState], None] | None = None,
) -> None:
    """Update the areas list in the Configuration window."""
    if not dpg.does_item_exist(app_state.areas.areas_list_tag):
        return

    # Clear existing children
    dpg.delete_item(app_state.areas.areas_list_tag, children_only=True)

    if not app_state.areas.named_areas:
        dpg.add_text("No areas defined", parent=app_state.areas.areas_list_tag)
        return

    for i, area in enumerate(app_state.areas.named_areas):
        with dpg.group(horizontal=False, parent=app_state.areas.areas_list_tag):
            with dpg.group(horizontal=True):
                dpg.add_text(f"{area.name}")

                def make_delete_callback(index: int) -> Callable[[int, None], None]:
                    def delete_area(_sender: int, _app_data: None) -> None:
                        deleted = delete_named_area(app_state, index)
                        if deleted is None:
                            return
                        redraw_area_overlays(app_state)
                        if on_areas_changed is not None:
                            on_areas_changed(app_state)
                        else:
                            update_areas_list(app_state)
                        schedule_settings_save(app_state)
                        update_status(app_state, f"Deleted area '{deleted.name}'")

                    return delete_area

                dpg.add_button(label="X", callback=make_delete_callback(i), width=25)

            # Show coordinates
            dpg.add_text(
                f"  ({area.x}, {area.y}) {area.width}x{area.height}",
                color=(150, 150, 150, 255),
            )

            # Show mark count if analysis mode is enabled
            if app_state.analysis.enabled:
                count = app_state.analysis.area_mark_counts.get(area.name, 0)
                dpg.add_text(
                    f"  Marks: {count}",
                    color=(255, 255, 0, 255),  # Yellow to stand out
                )

            dpg.add_separator()


def show_area_name_popup(
    app_state: AppState,
    bounds: tuple[int, int, int, int],
    on_areas_changed: Callable[[AppState], None] | None = None,
) -> None:
    """Show a popup to enter the name for a new area."""
    x, y, width, height = bounds

    popup_tag = "area_name_popup"
    input_tag = "area_name_input"

    # Delete existing popup if any
    if dpg.does_item_exist(popup_tag):
        dpg.delete_item(popup_tag)

    def on_confirm(_sender: int, _app_data: None) -> None:
        name = dpg.get_value(input_tag).strip()
        if not name:
            name = f"Area {len(app_state.areas.named_areas) + 1}"

        # Create the named area
        create_named_area(app_state, name, bounds)

        # Redraw overlays and update UI
        redraw_area_overlays(app_state)

        if on_areas_changed is not None:
            on_areas_changed(app_state)
        else:
            update_areas_list(app_state)

        schedule_settings_save(app_state)
        update_status(
            app_state, f"Created area '{name}' at ({x}, {y}) size {width}x{height}"
        )

        # Switch back to view mode
        app_state.areas.interaction_mode = "view"
        dpg.configure_item(app_state.areas.mode_button_tag, label="Create Area")

        # Close popup
        dpg.delete_item(popup_tag)

    def on_cancel(_sender: int, _app_data: None) -> None:
        app_state.areas.interaction_mode = "view"
        dpg.configure_item(app_state.areas.mode_button_tag, label="Create Area")
        dpg.delete_item(popup_tag)
        update_status(app_state, "Area creation cancelled")

    with dpg.window(
        label="Name Area",
        tag=popup_tag,
        modal=True,
        no_close=True,
        pos=(400, 300),
        width=300,
        height=120,
    ):
        dpg.add_text(f"Area: ({x}, {y}) size {width}x{height}")
        dpg.add_input_text(
            label="Name",
            tag=input_tag,
            default_value=f"Area {len(app_state.areas.named_areas) + 1}",
            width=200,
        )
        with dpg.group(horizontal=True):
            dpg.add_button(label="Create", callback=on_confirm)
            dpg.add_button(label="Cancel", callback=on_cancel)
