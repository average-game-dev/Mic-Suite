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

        # i tested the caps lock on linux, and im not dealing with the audio anymore than i need to, if a distro need special handling make a pull request or something
        
        import evdev
        from evdev import ecodes, InputDevice, list_devices

        # ---------------- Find all devices with keymod capability ----------------
        def _list_keymod_devices():
            devices = [InputDevice(path) for path in list_devices()]
            keymod_devices = []

            for dev in devices:
                caps = dev.capabilities()
                if ecodes.EV_KEY in caps:
                    keys = caps[ecodes.EV_KEY]
                    toggle_keys = {ecodes.KEY_CAPSLOCK, ecodes.KEY_NUMLOCK, ecodes.KEY_SCROLLLOCK}
                    if any(k in keys for k in toggle_keys):
                        keymod_devices.append(dev)
            return keymod_devices

        # ---------------- Pick the best candidate device ----------------
        def _pick_keyboard(devices):
            # Prefer USB keyboard
            usb_kb = [d for d in devices if 'usb' in (d.phys or '').lower()]
            named_kb = [d for d in usb_kb if 'keyboard' in (d.name or '').lower()]
            if named_kb:
                return named_kb[0]
            if usb_kb:
                return usb_kb[0]
            if devices:
                return devices[0]
            return None

        # ---------------- Internal setup ----------------
        _keymod_devices = _list_keymod_devices()
        _keyboard = _pick_keyboard(_keymod_devices)
        if not _keyboard:
            raise RuntimeError("No keyboard with keymod capability found!")

        # ---------------- API functions ----------------
        def is_numlock_on():
            """Return True if Num Lock is on"""
            return ecodes.LED_NUML in _keyboard.leds()

        def capslock_on():
            """Return True if Caps Lock is on"""
            return ecodes.LED_CAPSL in _keyboard.leds()

        def scrolllock_on():
            """Return True if Scroll Lock is on"""
            return ecodes.LED_SCROLLL in _keyboard.leds()
