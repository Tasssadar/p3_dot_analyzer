from p3_viewer import apply_colormap, ColormapID
from numpy.typing import NDArray
import numpy as np
import cv2
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RenderConfig:
    temp_min: float
    temp_max: float
    colormap: ColormapID


_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))


def _dde(
    img_u8: NDArray[np.uint8],
    strength: float = 0.5,
    kernel_size: int = 3,
) -> NDArray[np.uint8]:
    """Apply Digital Detail Enhancement (edge sharpening).
    Uses unsharp masking: enhanced = original + strength * (original - blurred)
    Args:
        img_u8: Input 8-bit image.
        strength: Enhancement strength (0.0-1.0, default 0.5).
        kernel_size: Kernel size for high-pass filter (default 3).
    Returns:
        Enhanced 8-bit image.
    """
    if strength <= 0:
        return img_u8
    # Create blurred version
    ksize = kernel_size | 1  # Ensure odd
    blurred = cv2.GaussianBlur(img_u8, (ksize, ksize), 0)
    # Unsharp mask
    img_f = img_u8.astype(np.float32)
    blurred_f = blurred.astype(np.float32)
    enhanced = img_f + strength * (img_f - blurred_f)
    return np.clip(enhanced, 0, 255).astype(np.uint8)


def _agc_fixed(
    config: RenderConfig,
    img: NDArray[np.uint16],
) -> NDArray[np.uint8]:
    """AGC with fixed temperature range (Celsius)."""
    raw_min = (config.temp_min + 273.15) * 64
    raw_max = (config.temp_max + 273.15) * 64
    normalized = (img.astype(np.float32) - raw_min) / (raw_max - raw_min)
    return (np.clip(normalized, 0.0, 1.0) * 255).astype(np.uint8)  # type: ignore


def render(
    config: RenderConfig, thermal: NDArray[np.uint16], width: int, height: int
) -> NDArray[np.float32]:
    """
    Renders raw thermal data to a texture for display in DearPyGUI.
    """
    img = _agc_fixed(config, thermal)

    # Cant use CLAHE - it changes colors, so they no longer match the temperature
    # Optional CLAHE for local contrast enhancement
    # clahe_result: Any = _clahe.apply(img)
    # Ensure result is a numpy array (CLAHE may return cv2.UMat on some platforms)
    # img = np.asarray(clahe_result, dtype=np.uint8)

    # DDE: edge enhancement
    img = _dde(img)
    img = apply_colormap(img, config.colormap)
    # transform for dearpygui
    img = np.asarray(
        cv2.resize(
            img,
            (width, height),
            interpolation=cv2.INTER_LINEAR,
        ),
        dtype=np.uint8,
    )
    texture = np.empty((height, width, 4), dtype=np.float32)
    texture[..., :3] = img[..., ::-1]  # BGR -> RGB
    texture[..., 3] = 255.0  # set alpha
    # normalize to 0-1 for dearpygui
    texture = texture.reshape(-1) / 255.0
    return texture
