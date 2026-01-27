from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from .models import AppState, NamedArea, NamedAreaData, SettingsData


def get_settings_path(base_dir: Path) -> Path:
    return base_dir / "settings.json"


def load_settings(path: Path) -> SettingsData | None:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data  # type: ignore[return-value]


def _clamp_int(value: Any, min_value: int, max_value: int) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(min_value, min(max_value, int(value)))
    return None


def _clamp_float(value: Any, min_value: float, max_value: float) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(min_value, min(max_value, float(value)))
    return None


def _parse_named_areas(value: Any) -> list[NamedArea]:
    if not isinstance(value, list):
        return []
    areas: list[NamedArea] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        x = entry.get("x")
        y = entry.get("y")
        width = entry.get("width")
        height = entry.get("height")
        if not isinstance(name, str):
            continue
        x_val = _clamp_int(x, 0, 10**9)
        y_val = _clamp_int(y, 0, 10**9)
        w_val = _clamp_int(width, 1, 10**9)
        h_val = _clamp_int(height, 1, 10**9)
        if x_val is None or y_val is None or w_val is None or h_val is None:
            continue
        areas.append(NamedArea(name=name, x=x_val, y=y_val, width=w_val, height=h_val))
    return areas


def apply_settings_to_state(app_state: AppState, settings: SettingsData) -> None:
    if "selected_color" in settings:
        color = settings["selected_color"]
        if color is None:
            app_state.selected_color = None
        elif isinstance(color, list) and len(color) == 3:
            r = _clamp_int(color[0], 0, 255)
            g = _clamp_int(color[1], 0, 255)
            b = _clamp_int(color[2], 0, 255)
            if r is not None and g is not None and b is not None:
                app_state.selected_color = (r, g, b)

    if "analysis_mode_enabled" in settings:
        if isinstance(settings["analysis_mode_enabled"], bool):
            app_state.analysis_mode_enabled = settings["analysis_mode_enabled"]

    if "color_tolerance" in settings:
        tolerance = _clamp_int(settings["color_tolerance"], 1, 100)
        if tolerance is not None:
            app_state.color_tolerance = tolerance

    if "min_area" in settings:
        min_area = _clamp_int(settings["min_area"], 10, 5000)
        if min_area is not None:
            app_state.min_area = min_area

    if "min_circularity" in settings:
        min_circularity = _clamp_float(settings["min_circularity"], 0.0, 1.0)
        if min_circularity is not None:
            app_state.min_circularity = min_circularity

    if "batch_sampling_rate" in settings:
        sampling = _clamp_int(settings["batch_sampling_rate"], 1, 100)
        if sampling is not None:
            app_state.batch_sampling_rate = sampling

    if "named_areas" in settings:
        app_state.named_areas = _parse_named_areas(settings["named_areas"])


def settings_from_state(app_state: AppState) -> SettingsData:
    named_areas: list[NamedAreaData] = [
        {
            "name": area.name,
            "x": area.x,
            "y": area.y,
            "width": area.width,
            "height": area.height,
        }
        for area in app_state.named_areas
    ]
    return {
        "selected_color": list(app_state.selected_color)
        if app_state.selected_color is not None
        else None,
        "analysis_mode_enabled": app_state.analysis_mode_enabled,
        "color_tolerance": app_state.color_tolerance,
        "min_area": app_state.min_area,
        "min_circularity": app_state.min_circularity,
        "batch_sampling_rate": app_state.batch_sampling_rate,
        "named_areas": named_areas,
    }


def save_settings(path: Path, app_state: AppState) -> None:
    data = settings_from_state(app_state)
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        return


def schedule_settings_save(app_state: AppState) -> None:
    if app_state.settings_path is None:
        return
    if app_state.settings_save_timer is not None:
        app_state.settings_save_timer.cancel()
    from threading import Timer

    timer = Timer(1.0, save_settings, args=(app_state.settings_path, app_state))
    timer.daemon = True
    app_state.settings_save_timer = timer
    timer.start()
