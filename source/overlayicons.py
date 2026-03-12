# overlay_hud.py
import os
import sys
import ctypes
import threading
import time
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QPainter

# --- Win32 Key States ---
user32 = ctypes.windll.user32
def capslock(): return user32.GetKeyState(0x14) & 1
def numlock(): return user32.GetKeyState(0x90) & 1
def scrolllock(): return user32.GetKeyState(0x91) & 1

# --- Absolute paths to PNG icons ---
BASE_DIR = os.path.join(os.path.dirname(__file__), "..", "overlaygraphics")
PNG_FILES = [
    os.path.join(BASE_DIR, "capslockON.png"),
    os.path.join(BASE_DIR, "capslockOFF.png"),
    os.path.join(BASE_DIR, "numlockON.png"),
    os.path.join(BASE_DIR, "numlockOFF.png"),
    os.path.join(BASE_DIR, "scrolllockON.png"),
    os.path.join(BASE_DIR, "scrolllockOFF.png"),
]

# --- Overlay Class ---
class Overlay(QWidget):
    def __init__(self, pngs, icon_size=90, spacing=10, xyoff=100, xyratio=0.5625):
        super().__init__()
        self.icon_size = icon_size
        self.spacing = spacing

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Load icons
        self.icons = [QPixmap(f) for f in pngs]

        # Set geometry: horizontal layout
        total_width = icon_size * 3 + spacing * 2  # 3 icons
    
        xoffset = 1920 - icon_size*3 - spacing*2 - xyoff
        yoffset = 1080 - icon_size - xyoff*xyratio

        self.setGeometry(xoffset, yoffset, total_width, icon_size)

        # Make click-through
        hwnd = int(self.winId())
        ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
        ctypes.windll.user32.SetWindowLongW(hwnd, -20, ex_style | 0x80000 | 0x20 | 0x08)

        # Timer to update overlay
        self.timer = QTimer()
        self.timer.timeout.connect(self.update)
        self.timer.start(25)

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.setOpacity(0.6)  # 0.0 = invisible, 1.0 = full opacity
        
        states = [capslock(), numlock(), scrolllock()]
        x = 0
        # Iterate each key
        for i, state in enumerate(states):
            pix = self.icons[i*2 + (0 if state else 1)]
            painter.drawPixmap(x, 0, self.icon_size, self.icon_size, pix)
            x += self.icon_size + self.spacing

# --- Run overlay in separate thread so Ctrl+C works ---
def run_overlay():
    app = QApplication([])
    overlay = Overlay(PNG_FILES, icon_size=90, spacing=7, xyoff=80, xyratio=0.8)
    overlay.show()
    app.exec()

if __name__ == "__main__":
    t = threading.Thread(target=run_overlay, daemon=True)
    t.start()
    try:
        while True:
            time.sleep(0.1)  # Main thread alive → Ctrl+C works
    except KeyboardInterrupt:
        print("Exiting overlay...")