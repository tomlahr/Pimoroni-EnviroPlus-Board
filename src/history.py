# history.py
# Zeitreihen-Verwaltung fuer main.py: kurze Trend-Deltas ("+0.3 C / 10 min")
# und der lange Ringpuffer fuer die Web-Sparklines. Getrennt von sensors.py,
# weil das hier reine Zeitverwaltung ist, keine Messung.

import time
from array import array


class Trend:
    """Delta zum aeltesten Punkt im Zeitfenster."""

    def __init__(self, window_ms, sample_ms):
        self.window_ms = window_ms
        self.sample_ms = sample_ms
        self._times = []
        self._values = []
        self._last_sample = 0

    def maybe_add(self, now, value):
        if self._times and time.ticks_diff(now, self._last_sample) < self.sample_ms:
            return
        self._last_sample = now
        self._times.append(now)
        self._values.append(value)
        while self._times and time.ticks_diff(now, self._times[0]) > self.window_ms:
            self._times.pop(0)
            self._values.pop(0)

    def delta(self):
        if len(self._values) < 2:
            return None
        span = time.ticks_diff(self._times[-1], self._times[0])
        if span < self.window_ms * 0.9:
            # Fenster noch nicht voll genug - sonst zeigt "/ 10 min" einen
            # Wert, der in Wirklichkeit nur ueber ein paar Sekunden/Minuten
            # gemessen wurde (z.B. direkt nach dem Boot).
            return None
        return self._values[-1] - self._values[0]


class History:
    """Ringpuffer je Messreihe. array('f') statt Listen - spart RAM
    (4 Werte x HISTORY_LEN Punkte x 4 Byte statt Python-Objekt-Overhead)."""

    def __init__(self, keys, length, interval_ms):
        self.length = length
        self.interval_ms = interval_ms
        self.keys = keys
        self._buf = {k: array("f", (0.0 for _ in range(length))) for k in keys}
        self._count = 0
        self._head = 0
        self._last_sample = 0

    def maybe_add(self, now, values):
        if self._count and time.ticks_diff(now, self._last_sample) < self.interval_ms:
            return
        self._last_sample = now
        for k in self.keys:
            self._buf[k][self._head] = values[k]
        self._head = (self._head + 1) % self.length
        if self._count < self.length:
            self._count += 1

    def iter_json(self, key, decimals=1, per=20):
        """Paket 2: wie series_json(), aber in kleinen Stuecken (je `per`
        Werte, ca. 100-150 Byte). web.py sendet jedes Stueck sofort - der
        groesste zusammenhaengende Speicherblock fuer /history sinkt von
        rund 3-4 kB (plus Kopie) auf wenige hundert Byte. Das entschaerft
        die Heap-Fragmentierung ("Block min" 4,8 kB am 24.09.)."""
        fmt = "{:." + str(decimals) + "f}"
        buf = self._buf[key]
        n = self._count
        start = self._head if n == self.length else 0
        yield "["
        i = 0
        while i < n:
            end = min(i + per, n)
            part = ",".join(fmt.format(buf[(start + j) % self.length])
                            for j in range(i, end))
            yield part if i == 0 else "," + part
            i = end
        yield "]"

# EOF 2026-09-26
