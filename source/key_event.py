import time
from pynput import keyboard
from pynput.keyboard import Controller, Key

kb = Controller()
running = True


# Function to listen for Esc
def on_press(key):
    global running
    if key == Key.esc:
        running = False
        return False  # Stop listener


# Start listener in background
listener = keyboard.Listener(on_press=on_press)
listener.start()

print("Press ESC to stop...")

# Loop: Ctrl+V + Enter every 10ms
while running:
    kb.press(Key.ctrl)
    kb.press('v')
    kb.release('v')
    kb.release(Key.ctrl)

    kb.press(Key.enter)
    kb.release(Key.enter)

    time.sleep(0.01)  # 10 milliseconds

listener.join()
print("Stopped.")
