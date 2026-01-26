from __future__ import annotations

from collections.abc import Callable

import cv2
import dearpygui.dearpygui as dpg  # type: ignore

from .models import AppState, IMAGES_PER_SECOND


def update_status(app_state: AppState, message: str) -> None:
    """Update the status text display."""
    dpg.set_value(app_state.status_text_tag, message)


def update_filename_label(app_state: AppState) -> None:
    """Update the filename label with the current image path."""
    current_path = app_state.repo.get_current_path()
    if current_path is None:
        dpg.set_value(app_state.filename_text_tag, "No image selected")
        return
    dpg.set_value(app_state.filename_text_tag, f"{current_path.name}")


def update_timestamp_label(app_state: AppState) -> None:
    """Update the timestamp label based on the current image index."""
    if app_state.repo.count() == 0:
        dpg.set_value(app_state.timestamp_text_tag, "Timestamp: n/a")
        return
    current_index = app_state.repo.get_current_index()
    timestamp = current_index / IMAGES_PER_SECOND
    dpg.set_value(app_state.timestamp_text_tag, f"Timestamp: {timestamp:.2f} s")


def update_slider_range(app_state: AppState) -> None:
    """Update the slider range based on the number of images."""
    count = app_state.repo.count()
    if count == 0:
        dpg.configure_item(
            app_state.slider_tag,
            min_value=0,
            max_value=0,
            default_value=0,
            enabled=False,
        )
    else:
        current_index = app_state.repo.get_current_index()
        dpg.configure_item(
            app_state.slider_tag,
            min_value=0,
            max_value=count - 1,
            default_value=current_index,
            enabled=True,
        )


def screen_to_image_coords(
    app_state: AppState, screen_x: float, screen_y: float
) -> tuple[int, int]:
    """Convert screen coordinates to image pixel coordinates.

    Returns clamped coordinates if outside the image bounds.
    """
    # Get drawlist screen position
    dl_pos = dpg.get_item_rect_min(app_state.image_drawlist_tag)

    # Convert to local drawlist coords
    local_x = screen_x - dl_pos[0]
    local_y = screen_y - dl_pos[1]

    # Bounds check against current image dimensions
    if local_x < 0 or local_y < 0:
        return (0, 0)
    if (
        local_x >= app_state.current_image_width
        or local_y >= app_state.current_image_height
    ):
        return (app_state.current_image_width, app_state.current_image_height)

    return (int(local_x), int(local_y))


def sample_color_at(
    app_state: AppState, img_x: int, img_y: int
) -> tuple[int, int, int] | None:
    """Sample the RGB color at the given image coordinates."""
    if app_state.current_image_data is None:
        return None

    # Bounds check
    h, w = app_state.current_image_data.shape[:2]
    if img_x < 0 or img_x >= w or img_y < 0 or img_y >= h:
        return None

    # OpenCV loads images in BGR format
    bgr = app_state.current_image_data[img_y, img_x]
    # Convert to RGB
    return (int(bgr[2]), int(bgr[1]), int(bgr[0]))


def update_color_display(app_state: AppState) -> None:
    """Update the color swatch and text display with the selected color."""
    if app_state.selected_color is None:
        dpg.set_value(app_state.color_text_tag, "No color selected")
        # Draw a gray swatch to indicate no selection
        dpg.configure_item(
            app_state.color_swatch_tag,
            fill=(128, 128, 128, 255),
        )
    else:
        r, g, b = app_state.selected_color
        dpg.set_value(app_state.color_text_tag, f"RGB({r}, {g}, {b})")
        # Update the swatch color
        dpg.configure_item(
            app_state.color_swatch_tag,
            fill=(r, g, b, 255),
        )


def show_image_at_current_index(
    app_state: AppState,
    on_image_loaded: Callable[[AppState], None] | None = None,
) -> None:
    """Load and display the current image from the repository.

    Args:
        app_state: The application state.
        on_image_loaded: Optional callback called after image is loaded,
            typically used to redraw overlays.
    """
    path = app_state.repo.get_current_path()
    if path is None:
        update_status(app_state, "No images found in 'imgs' directory.")
        update_filename_label(app_state)
        update_timestamp_label(app_state)
        app_state.current_image_data = None
        app_state.current_image_width = 0
        app_state.current_image_height = 0
        return

    width, height, _channels, pixel_data = dpg.load_image(str(path))

    # Cache image data for color sampling (OpenCV loads as BGR)
    app_state.current_image_data = cv2.imread(str(path))
    app_state.current_image_width = width
    app_state.current_image_height = height

    # Update the dynamic texture and draw command
    dpg.configure_item(app_state.texture_tag, width=width, height=height)
    dpg.set_value(app_state.texture_tag, pixel_data)

    # Draw image from (0, 0) to (width, height) in the drawlist's space
    dpg.configure_item(app_state.image_draw_tag, pmin=(0, 0), pmax=(width, height))

    # Call optional callback (e.g., to redraw area overlays)
    if on_image_loaded is not None:
        on_image_loaded(app_state)

    update_status(
        app_state,
        f"Showing image {app_state.repo.get_current_index() + 1} of {app_state.repo.count()}",
    )
    update_filename_label(app_state)
    update_timestamp_label(app_state)
