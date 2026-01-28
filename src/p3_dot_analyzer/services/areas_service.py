from __future__ import annotations

from ..models import NamedArea
from ..state import AppState


def create_named_area(
    app_state: AppState,
    name: str,
    bounds: tuple[int, int, int, int],
) -> NamedArea:
    x, y, width, height = bounds
    area = NamedArea(name=name, x=x, y=y, width=width, height=height)
    app_state.areas.named_areas.append(area)
    return area


def delete_named_area(app_state: AppState, index: int) -> NamedArea | None:
    if 0 <= index < len(app_state.areas.named_areas):
        return app_state.areas.named_areas.pop(index)
    return None
