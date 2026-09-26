# system.py
# Misst den Pico selbst, nicht die Umwelt - bewusst getrennt von sensors.py.
# Wird von der System-Seite in display.py und spaeter vom Webserver genutzt.

import gc
import os
import machine

_RESET_CAUSE_NAMES = (
    ("PWRON_RESET", "Power-On"),
    ("HARD_RESET", "Hard-Reset"),
    ("WDT_RESET", "Watchdog"),
    ("DEEPSLEEP_RESET", "Deep-Sleep"),
    ("SOFT_RESET", "Soft-Reset"),
)
_RESET_CAUSES = {}
for _name, _label in _RESET_CAUSE_NAMES:
    if hasattr(machine, _name):
        _RESET_CAUSES[getattr(machine, _name)] = _label


class SystemStats:
    """Haelt die ueber die Laufzeit beobachteten RAM-Tiefstaende fest.
    Session-basiert, wie die Sensor-Min/Max-Werte - kein Flash-Verschleiss."""

    def __init__(self):
        self.mem_free_min = None
        self.block = None
        self.block_min = None

    def sample(self):
        gc.collect()
        free = gc.mem_free()
        if self.mem_free_min is None or free < self.mem_free_min:
            self.mem_free_min = free
        return free

    def probe_block(self):
        """Groessten zusammenhaengenden freien Heap-Block messen.
        mem_free() zeigt nur die Summe aller Luecken - bei fragmentiertem
        Heap kann genug frei sein und trotzdem jede groessere Allokation
        scheitern. Genau das misst diese Sonde."""
        gc.collect()
        self.block = largest_free_block()
        if self.block_min is None or self.block < self.block_min:
            self.block_min = self.block
        return self.block


def largest_free_block(step=256):
    """Binaersuche per Probe-Allokation. Jeder Fehlversuch kostet intern
    eine Garbage Collection - deshalb nur alle paar Sekunden aufrufen."""
    lo, hi = 0, gc.mem_free()
    while hi - lo > step:
        mid = (lo + hi) // 2
        try:
            b = bytearray(mid)
            del b
            lo = mid
        except MemoryError:
            hi = mid
    return lo


def reset_cause():
    return _RESET_CAUSES.get(machine.reset_cause(), "unbekannt")


def flash_free_kb():
    try:
        st = os.statvfs("/")
        return (st[0] * st[3]) // 1024
    except Exception:
        return None


def firmware_info():
    u = os.uname()
    return "{} {}".format(u.sysname, u.release)


def wlan_rssi(wlan):
    """wlan: aktives network.WLAN(STA_IF) oder None, falls nicht verbunden."""
    if wlan is None or not wlan.isconnected():
        return None
    try:
        return wlan.status("rssi")
    except Exception:
        return None

# EOF 2026-09-23
