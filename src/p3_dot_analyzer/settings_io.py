from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from p3_viewer import ColormapID  # type: ignore

from .models import NamedArea, NamedAreaData, SettingsData
from .state import AppState


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


def _normalize_render_range(app_state: AppState) -> None:
    if app_state.render.temp_max <= app_state.render.temp_min:
        app_state.render.temp_max = app_state.render.temp_min + 0.1


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
    if "selected_temp" in settings:
        temp = _clamp_float(settings["selected_temp"], -100.0, 1000.0)
        if temp is not None:
            app_state.analysis.selected_temp = temp

    if "analysis_mode_enabled" in settings:
        if isinstance(settings["analysis_mode_enabled"], bool):
            app_state.analysis.enabled = settings["analysis_mode_enabled"]

    if "color_tolerance" in settings:
        tolerance = _clamp_int(settings["color_tolerance"], 1, 100)
        if tolerance is not None:
            app_state.analysis.color_tolerance = tolerance

    if "min_area" in settings:
        min_area = _clamp_int(settings["min_area"], 10, 5000)
        if min_area is not None:
            app_state.analysis.min_area = min_area

    if "min_circularity" in settings:
        min_circularity = _clamp_float(settings["min_circularity"], 0.0, 1.0)
        if min_circularity is not None:
            app_state.analysis.min_circularity = min_circularity

    if "batch_sampling_rate" in settings:
        sampling = _clamp_int(settings["batch_sampling_rate"], 1, 100)
        if sampling is not None:
            app_state.analysis.batch_sampling_rate = sampling

    if "named_areas" in settings:
        app_state.areas.named_areas = _parse_named_areas(settings["named_areas"])

    if "render_temp_min" in settings:
        temp_min = _clamp_float(settings["render_temp_min"], -100.0, 1000.0)
        if temp_min is not None:
            app_state.render.temp_min = temp_min

    if "render_temp_max" in settings:
        temp_max = _clamp_float(settings["render_temp_max"], -100.0, 1000.0)
        if temp_max is not None:
            app_state.render.temp_max = temp_max

    if "render_colormap" in settings:
        name = settings["render_colormap"]
        if isinstance(name, str):
            mapping = {colormap.name: colormap for colormap in ColormapID}
            if name in mapping:
                app_state.render.colormap = mapping[name]

    _normalize_render_range(app_state)


def settings_from_state(app_state: AppState) -> SettingsData:
    named_areas: list[NamedAreaData] = [
        {
            "name": area.name,
            "x": area.x,
            "y": area.y,
            "width": area.width,
            "height": area.height,
        }
        for area in app_state.areas.named_areas
    ]
    return {
        "selected_temp": app_state.analysis.selected_temp,
        "analysis_mode_enabled": app_state.analysis.enabled,
        "color_tolerance": app_state.analysis.color_tolerance,
        "min_area": app_state.analysis.min_area,
        "min_circularity": app_state.analysis.min_circularity,
        "batch_sampling_rate": app_state.analysis.batch_sampling_rate,
        "named_areas": named_areas,
        "render_temp_min": app_state.render.temp_min,
        "render_temp_max": app_state.render.temp_max,
        "render_colormap": app_state.render.colormap.name,
    }


def save_settings(path: Path, app_state: AppState) -> None:
    data = settings_from_state(app_state)
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        return


def schedule_settings_save(app_state: AppState) -> None:
    if app_state.settings.path is None:
        return
    if app_state.settings.save_timer is not None:
        app_state.settings.save_timer.cancel()
    from threading import Timer

    timer = Timer(1.0, save_settings, args=(app_state.settings.path, app_state))
    timer.daemon = True
    app_state.settings.save_timer = timer
    timer.start()
