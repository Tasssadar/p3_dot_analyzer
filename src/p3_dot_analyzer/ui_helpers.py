from __future__ import annotations

from collections.abc import Callable

import dearpygui.dearpygui as dpg  # type: ignore

from .camera import CamFrame, RENDER_SCALE
from .state import AppState
from datetime import datetime

from p3_camera import EnvParams, raw_to_celsius_corrected  # type: ignore[import-untyped]


def update_status(app_state: AppState, message: str) -> None:
    """Update the status text display."""
    dpg.set_value(app_state.ui.status_text_tag, message)


def update_recording_camera_status(app_state: AppState, message: str) -> None:
    """Update the camera status text on the recording tab."""
    dpg.set_value(app_state.recording.camera_status_tag, message)


def screen_to_image_coords(
    app_state: AppState, screen_x: float, screen_y: float
) -> tuple[int, int]:
    """Convert screen coordinates to image pixel coordinates.

    Returns clamped coordinates if outside the image bounds.
    """
    if app_state.render.current_frame is None:
        return (0, 0)

    # Get drawlist screen position
    dl_pos = dpg.get_item_rect_min(app_state.ui.image_drawlist_tag)

    # Convert to local drawlist coords
    local_x = screen_x - dl_pos[0]
    local_y = screen_y - dl_pos[1]

    # Bounds check against current image dimensions
    if local_x < 0 or local_y < 0:
        return (0, 0)
    if (
        local_x >= app_state.render.current_frame.width
        or local_y >= app_state.render.current_frame.height
    ):
        return (
            app_state.render.current_frame.width,
            app_state.render.current_frame.height,
        )

    return (int(local_x), int(local_y))


def get_temp_at(app_state: AppState, img_x: int, img_y: int) -> float | None:
    """Get the temperature at the given image coordinates."""
    if app_state.render.current_frame is None:
        return None

    return get_temp_at_img(app_state, app_state.render.current_frame, img_x, img_y)


def get_temp_at_img(
    app_state: AppState, frame: CamFrame, img_x: int, img_y: int
) -> float | None:
    """Get the temperature at the given image coordinates."""
    # Bounds check
    h = frame.height
    w = frame.width
    if img_x < 0 or img_x >= w or img_y < 0 or img_y >= h:
        return None

    img_y = img_y // RENDER_SCALE
    img_x = img_x // RENDER_SCALE

    env = EnvParams(
        emissivity=app_state.render.emissivity,
        reflected_temp=app_state.render.reflected_temp,
    )
    return float(
        raw_to_celsius_corrected(
            float(frame.raw_thermal[img_y, img_x]),
            env,
        )
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
            app_state.ui.timestamp_text_tag,
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
