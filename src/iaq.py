# iaq.py
# Relative Luftqualitaet aus dem Gaswiderstand (BME688/BME690).
# Paket 2 (2026-09-26): gemeinsames Modul fuer Enviro+ und BME690 - beide
# Projekte enthalten diese Datei identisch.
#
# Prinzip: Zwei Huellkurven ueber den Gaswiderstand.
#   hi = "saubere Luft"   (hoechster Wert der juengeren Vergangenheit)
#   lo = "belastete Luft" (niedrigster Wert der juengeren Vergangenheit)
# Score = Lage des aktuellen Werts zwischen lo und hi, logarithmisch
# (Gaswiderstand faellt bei Belastung etwa exponentiell), 0.0 .. 1.0.
#
# Unterschiede zur alten Logik:
#   - Zerfall nach ZEIT (Halbwertszeit in Stunden), nicht pro Messung -
#     der Messtakt spielt keine Rolle mehr.
#   - Mindestspanne als Verhaeltnis hi/lo >= IAQ_MIN_RATIO. Reicht die
#     beobachtete Spanne nicht, wird lo abgesenkt, hi bleibt: gleichbleibend
#     gute Luft zeigt "gut" statt "kalibriert...".
#   - Sperrfrist nach dem Start (IAQ_WARMUP_S): der kalte Heizer liefert
#     anfangs zu niedrige Werte, die frueher die Baseline verdarben.
#   - Baseline auf Flash (IAQ_BASELINE_FILE, Format "lo,hi"), kompatibel
#     mit der bisherigen iaq_baseline.txt des Enviro+.

import math
import time

import config

_MAX_DT_S = 60      # Luecken (z. B. Sensorfehler) zaehlen hoechstens so lange


class IAQ:
    def __init__(self):
        self.ratio = config.IAQ_MIN_RATIO
        self.halflife_s = config.IAQ_HALFLIFE_H * 3600
        self.warmup_ms = config.IAQ_WARMUP_S * 1000
        self.file = config.IAQ_BASELINE_FILE
        self.lo = None
        self.hi = None
        self._t_start = time.ticks_ms()
        self._t_last = None
        self._load()

    # --- Flash --------------------------------------------------------------

    def _load(self):
        try:
            with open(self.file) as f:
                lo, hi = f.read().split(",")
            lo, hi = float(lo), float(hi)
            if 0 < lo < hi:
                self.lo, self.hi = lo, hi
                self._enforce_ratio()
        except Exception:
            self.lo = self.hi = None

    def save(self):
        if self.lo is None:
            return
        try:
            with open(self.file, "w") as f:
                f.write("{:.1f},{:.1f}".format(self.lo, self.hi))
        except Exception:
            pass

    # --- Lernen -------------------------------------------------------------

    def _enforce_ratio(self):
        if self.hi / self.lo < self.ratio:
            self.lo = self.hi / self.ratio

    @property
    def warming_up(self):
        return time.ticks_diff(time.ticks_ms(), self._t_start) < self.warmup_ms

    def update(self, gas_kohm, valid):
        """Nach jeder Messung aufrufen. valid: Gaswert gueltig und Heizer
        stabil (beide Statusbits)."""
        now = time.ticks_ms()
        last, self._t_last = self._t_last, now
        if self.warming_up or not valid or gas_kohm is None or gas_kohm <= 0:
            return
        if self.lo is None:
            self.hi = gas_kohm
            self.lo = gas_kohm / self.ratio
            return
        dt = _MAX_DT_S if last is None else min(time.ticks_diff(now, last) / 1000, _MAX_DT_S)
        keep = math.exp(-0.6931 * dt / self.halflife_s)   # 0.5 ** (dt / T_half)
        # Huellkurven: neuer Extremwert sofort, sonst langsam zum Messwert hin.
        if gas_kohm >= self.hi:
            self.hi = gas_kohm
        else:
            self.hi = gas_kohm + (self.hi - gas_kohm) * keep
        if gas_kohm <= self.lo:
            self.lo = gas_kohm
        else:
            self.lo = gas_kohm + (self.lo - gas_kohm) * keep
        self._enforce_ratio()

    # --- Auswerten ----------------------------------------------------------

    @property
    def ready(self):
        return self.lo is not None and not self.warming_up

    def score(self, gas_kohm):
        """0.0 (belastet) .. 1.0 (sauber) oder None (Aufwaermphase/ohne Daten)."""
        if not self.ready or gas_kohm is None or gas_kohm <= 0:
            return None
        s = math.log(gas_kohm / self.lo) / math.log(self.hi / self.lo)
        return 0.0 if s < 0.0 else (1.0 if s > 1.0 else s)

# EOF 2026-09-26
