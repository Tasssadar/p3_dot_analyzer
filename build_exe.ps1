uv run pyinstaller -F -y -w --collect-all p3_dot_analyzer --hidden-import dearpygui.dearpygui --hidden-import cv2 --add-data libusb0.dll:. .\p3_dot_analyzer_cli.py
