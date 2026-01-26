from p3_camera import Model, P3Camera, get_model_config, raw_to_celsius
from pathlib import Path
import cv2
import time

OUTPUT_DIR = Path("img_output")
TEMP_MIN = 10
TEMP_MAX = 50

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

try:
    camera = P3Camera()
    camera.connect()
    camera.init()
    camera.start_streaming()
    time.sleep(0.1)
    frame_counter = 0
    while True:
        ir_brightness, thermal_raw = camera.read_frame_both()
        time.sleep(0.1)
        if thermal_raw is None:
            continue
        frame_counter += 1
        temps_celsius = raw_to_celsius(thermal_raw)

        # relative_temps = temps_celsius.copy()
        # relative_temps[relative_temps < TEMP_MIN] = TEMP_MIN
        ##relative_temps[relative_temps > TEMP_MAX] = TEMP_MAX
        # relative_temps = (relative_temps - TEMP_MIN) / (TEMP_MAX - TEMP_MIN) * 255

        img_name = f"img_{frame_counter:05d}.png"
        # cv2.imwrite(str(OUTPUT_DIR / img_name), relative_temps)
        cv2.imwrite(str(OUTPUT_DIR / img_name), temps_celsius)
        print(f"Ulozeno {img_name}")
finally:
    camera.stop_streaming()
    camera.disconnect()
