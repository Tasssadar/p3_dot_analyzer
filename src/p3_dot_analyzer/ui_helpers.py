from __future__ import annotations

from collections.abc import Callable

import dearpygui.dearpygui as dpg  # type: ignore

from .camera import CamFrame, RENDER_SCALE
from .models import AppState
from datetime import datetime

from p3_camera import raw_to_celsius
from p3_viewer import get_colormap


def update_status(app_state: AppState, message: str) -> None:
    """Update the status text display."""
    dpg.set_value(app_state.status_text_tag, message)


def screen_to_image_coords(
    app_state: AppState, screen_x: float, screen_y: float
) -> tuple[int, int]:
    """Convert screen coordinates to image pixel coordinates.

    Returns clamped coordinates if outside the image bounds.
    """
    if app_state.current_frame is None:
        return (0, 0)

    # Get drawlist screen position
    dl_pos = dpg.get_item_rect_min(app_state.image_drawlist_tag)

    # Convert to local drawlist coords
    local_x = screen_x - dl_pos[0]
    local_y = screen_y - dl_pos[1]

    # Bounds check against current image dimensions
    if local_x < 0 or local_y < 0:
        return (0, 0)
    if (
        local_x >= app_state.current_frame.width
        or local_y >= app_state.current_frame.height
    ):
        return (app_state.current_frame.width, app_state.current_frame.height)

    return (int(local_x), int(local_y))


def get_temp_at(app_state: AppState, img_x: int, img_y: int) -> float | None:
    """Get the temperature at the given image coordinates."""
    if app_state.current_frame is None:
        return None

    # Bounds check
    h = app_state.current_frame.height
    w = app_state.current_frame.width
    if img_x < 0 or img_x >= w or img_y < 0 or img_y >= h:
        return None

    img_y = img_y // RENDER_SCALE
    img_x = img_x // RENDER_SCALE

    return float(
        raw_to_celsius(float(app_state.current_frame.raw_thermal[img_y, img_x]))
    )


def color_for_temp(app_state: AppState, temp: float) -> tuple[int, int, int]:
    raw_min = app_state.render_temp_min
    raw_max = app_state.render_temp_max
    normalized = int(min(1.0, max(0.0, (temp - raw_min) / (raw_max - raw_min))) * 255)

    bgr = get_colormap(app_state.render_colormap)[normalized]

    return int(bgr[2]), int(bgr[1]), int(bgr[0])


def update_color_display(app_state: AppState) -> None:
    """Update the swatch and text display with the selected temperature."""
    if app_state.selected_temp is None:
        dpg.set_value(app_state.color_text_tag, "No temperature selected")
        # Draw a gray swatch to indicate no selection
        dpg.configure_item(
            app_state.color_swatch_tag,
            fill=(128, 128, 128, 255),
        )
    else:
        r, g, b = color_for_temp(app_state, app_state.selected_temp)
        dpg.set_value(
            app_state.color_text_tag, f"Temp: {app_state.selected_temp:.2f} C"
        )
        # Update the swatch color
        dpg.configure_item(
            app_state.color_swatch_tag,
            fill=(r, g, b, 255),
        )


def render_frame(
    app_state: AppState,
    frame: CamFrame,
    texture_tag: str,
    draw_tag: str,
    update_timestamp: bool = True,
    on_image_loaded: Callable[[AppState], None] | None = None,
) -> None:
    """Load and display a frame into a specific texture/draw target."""

    if update_timestamp:
        dpg.set_value(
            app_state.timestamp_text_tag,
            datetime.fromtimestamp(frame.ts).strftime("%Y-%m-%d %H:%M:%S"),
        )

    dpg.configure_item(
        texture_tag,
        width=frame.width,
        height=frame.height,
    )
    dpg.set_value(texture_tag, frame.img)

    if dpg.does_item_exist(draw_tag):
        dpg.configure_item(
            draw_tag,
            pmin=(0, 0),
            pmax=(frame.width, frame.height),
        )

    if on_image_loaded is not None:
        on_image_loaded(app_state)
