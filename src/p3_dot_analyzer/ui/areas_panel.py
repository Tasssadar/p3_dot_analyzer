from __future__ import annotations

from collections.abc import Callable

import dearpygui.dearpygui as dpg  # type: ignore

from ..state import AppState


def build_named_areas_controls(
    state: AppState, on_mode_button_clicked: Callable[[int, None, AppState], None]
) -> None:
    dpg.add_separator()
    with dpg.group(horizontal=True):
        dpg.add_text("Named Areas:")
        dpg.add_button(
            label="Create Area",
            callback=on_mode_button_clicked,
            user_data=state,
            tag=state.areas.mode_button_tag,
        )
    dpg.add_text("(Click 'Create Area' then drag on image)")
    dpg.add_separator()

    # Areas list container
    with dpg.child_window(
        tag=state.areas.areas_list_tag,
        height=250,
        border=True,
    ):
        dpg.add_text("No areas defined")
