import os

match os.name:
    case "nt":
        import ctypes

        def is_numlock_on():
            return bool(ctypes.windll.user32.GetKeyState(0x90) & 1)
        def capslock_on():
            return bool(ctypes.windll.user32.GetKeyState(0x14) & 1)
        def scrolllock_on():
            return bool(ctypes.windll.user32.GetKeyState(0x91) & 1)
    case "posix":        
        import select
        from evdev import InputDevice, list_devices, ecodes
        import threading

        _scrolllock = False
        _capslock   = False
        _numlock    = False

        def run(devices, keymap):
            while True:
                r, _, _ = select.select(devices, [], [])

                for dev in r:
                    for event in dev.read():
                        if event.type != ecodes.EV_KEY:
                            continue

                        if event.value != 1:
                            continue

                        fn = keymap.get(event.code)
                        if fn:
                            fn(dev, event)


        devices = [InputDevice(p) for p in list_devices()]
        
        def __scrolllock_pressed(d1, d2):
            global _scrolllock
            _scrolllock = not _scrolllock
        def __numlock_pressed(d1, d2):
            global _numlock
            _numlock = not _numlock
        def __capslock_pressed(d1, d2):
            global _capslock
            _capslock = not _capslock


        __listener = threading.Thread(target = run, args = 
            (devices, {
                ecodes.KEY_SCROLLLOCK: __scrolllock_pressed,
                ecodes.KEY_CAPSLOCK: __capslock_pressed,
                ecodes.KEY_NUMLOCK: __numlock_pressed,
                }
            )
        )

        __listener.daemon = True

        __listener.start()

        def is_numlock_on():
            return _numlock
        def capslock_on():
            return _capslock
        def scrolllock_on():
            return _scrolllock
        
if __name__ == "__main__":
    import time

    try:
        while True:
            print(f"Numlock: {is_numlock_on()}\nCapslock: {capslock_on()}\nScrollock: {scrolllock_on()}")
            time.sleep(0.1)
    except KeyboardInterrupt as e:
        print("Exiting")