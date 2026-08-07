"""Device-kind detection.

MobileWorld was built for the Android emulator (device id 'emulator-5554', a QEMU
console behind `adb emu ...`). It can also run against a redroid container, which has
NO emulator console, NO qemu process, and reaches the network adb device by a
host:port id (e.g. 'host.docker.internal:5555' or 'localhost:5555').

`is_redroid()` lets call sites branch so the emulator code path is preserved exactly
while redroid gets a container-appropriate path.
"""

import os


def is_redroid(device: str | None = None) -> bool:
    """Return True when the target is a redroid (container) device rather than a QEMU emulator.

    Heuristic: the QEMU emulator's adb id always starts with 'emulator-' (e.g.
    'emulator-5554'); a network/redroid device is addressed as '<host>:<port>'.
    An explicit override `MOBILE_WORLD_BACKEND=redroid|emulator` wins if set.
    """
    override = os.environ.get("MOBILE_WORLD_BACKEND", "").strip().lower()
    if override in ("redroid", "container"):
        return True
    if override in ("emulator", "qemu", "avd"):
        return False
    dev = (device or os.environ.get("ANDROID_DEVICE", "") or "").strip()
    if not dev:
        return False
    return not dev.startswith("emulator-")
