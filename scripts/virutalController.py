import time
import vgamepad as vg

pad = vg.VX360Gamepad()

def tap(button, frames=3):
    pad.press_button(button)
    pad.update()
    time.sleep(frames / 60)   # SF6 runs at 60 fps
    pad.release_button(button)
    pad.update()
    time.sleep(1 / 60)

tap(vg.XUSB_BUTTON.XUSB_GAMEPAD_A)   # e.g. a light punch, depending on your bindings