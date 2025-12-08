import ctypes
import tkinter as tk
import threading as t
import sounddevice as sd
import numpy as np

# ---------------- Flags, locks and values ----------------
stop_event = t.Event()
volume: float = 0

blocksize: int = 1024
samplerate: int = 48000

# ---------------- Win32 / Tk helpers ----------------
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WS_EX_LAYERED = 0x80000
WS_EX_TOOLWINDOW = 0x00000080  # hide from alt-tab / taskbar

def make_window_clickthrough(hwnd):
    style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

def rgb(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

# ---------------- Visual overlay (tkinter) ----------------
def create_overlay():
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    # Use a color we will treat as transparent
    root.attributes('-transparentcolor', 'black')
    root.configure(bg='black')
    root.geometry('360x24+50+80')

    canvas = tk.Canvas(root, width=360, height=24, bg='black', highlightthickness=0)
    canvas.pack()

    # Make click-through
    root.update_idletasks()
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    make_window_clickthrough(hwnd)

    def update_meter():
        canvas.delete("all")
        vol = volume * 2
        fill_len = int(min(max(vol * 1000.0, 0.0), 360))
        if vol < 0.2:
            color = rgb(10, 255, 18)
        elif vol < 0.4:
            color = rgb(255, 218, 10)
        else:
            color = rgb(255, 10, 10)
        # draw background faint bar (semi-visual guide)
        canvas.create_rectangle(0, 0, 360, 24, outline='', fill='')
        canvas.create_rectangle(0, 0, fill_len, 24, fill=color, outline='')
        if not stop_event.is_set():
            root.after(30, update_meter)  # schedule again
        else:
            try:
                root.destroy()
            except Exception:
                pass

    def check_stop():
        if stop_event.is_set():
            root.destroy()  # gracefully exit
        else:
            root.after(50, check_stop)  # check again in 50ms
            
    root.after(0, update_meter)
    return root

def callback(INbinGLE, bingle, bingleovertime, BONGLE):
    global volume

    if BONGLE:
        print(BONGLE)
    volume = np.sqrt(np.mean(INbinGLE**2))

def main():

    print("=== Input Devices ===")
    for idx, d in enumerate(sd.query_devices()):
        if d['max_input_channels'] != 0:
            print(f"[{idx}] {d['name']} (hostapi={d['hostapi']}) (I/O: {d['max_input_channels']}/{d['max_output_channels']})")

    dev1 = int(input("Enter the loopback device INPUT: "))

    with sd.InputStream(channels=2, callback=callback, samplerate=samplerate, blocksize=blocksize, device=dev1):
        root = create_overlay()
        root.mainloop()

if __name__ == "__main__":
    main()