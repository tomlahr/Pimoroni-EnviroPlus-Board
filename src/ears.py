# ears.py
# Geraeuschreaktion fuer den Augen-Bildschirmschoner. Wertet den Mikrofon-
# Pegel (dBFS) relativ zum Grundrauschen aus und liefert einen Zustand:
#
#   ""         nichts Besonderes
#   "listen"   deutlich lauter als sonst (Sprache, TV): aufmerksamer Blick
#   "startle"  ploetzlicher Knall (Klatschen, Tuer): kurz weit aufgerissen
#   "annoyed"  lange anhaltender Laerm: genervt
#   "pfiff"    Cat-Call: reiner Ton mit Tonhoehenverlauf (Herzaugen, Kussmund)
#
# Nachts (sleeping=True) gibt es nur ein Ereignis: laute Spitzen setzen
# take_wake() - die Augen oeffnen kurz ein Auge und schlafen weiter.
#
# Grundrauschen (Huellkurve, wie die IAQ-Baseline): faellt schnell (ein Viertel
# des Abstands pro Messung) auf niedrigere Pegel und steigt nur langsam wieder - in ruhiger Umgebung
# schneller, bei anhaltendem Laerm sehr langsam (Gewoehnung nach ~1 h).
#
# Speicher: Alles in ganzzahligen Hundertstel-dB (Pegel x 100). Keine Listen,
# keine Floats pro Messung - der Heap bleibt unberuehrt.
#
# Messgrundlage (Schreibtisch, 2026-11-15): Ruhe median -70,7 dBFS
# (p10..p90 -71,2..-70,0), Sprechen median -62,7 / max -51,9, TV median
# -64,3 / max -57,7, Klatschen max -17,5, Tuer max -24,6.

import time

import config


def _cdb(db):
    return int(db * 100)


class Ears:
    def __init__(self):
        c = config
        self._on = _cdb(c.EARS_LISTEN_ON_DB)
        self._off = _cdb(c.EARS_LISTEN_OFF_DB)
        self._startle = _cdb(c.EARS_STARTLE_DB)
        self._jump = _cdb(c.EARS_JUMP_DB)
        self._wake_db = _cdb(c.EARS_WAKE_DB)
        self._lo = _cdb(c.EARS_BASE_RANGE[0])
        self._hi = _cdb(c.EARS_BASE_RANGE[1])
        self._rise_q = int(c.EARS_RISE_QUIET_DB_MIN * 100)   # cdB pro Minute
        self._rise_l = int(c.EARS_RISE_LOUD_DB_MIN * 100)
        self.state = ""
        self.base = None            # Grundrauschen in cdB
        self._prev = 0
        self._d1 = 0                # die beiden Vor-Deltas fuer den Median
        self._d2 = 0
        self._acc = 0               # Zeitsumme fuer den langsamen Anstieg
        self._t = 0
        self._listen = False
        self._loud_since = 0
        self._last_loud = 0
        self._startle_until = 0
        self._lock = 0              # bis dahin kein neues Ereignis
        self._wake = False
        # Pfiff: Folge reiner Tonmessungen (tone.py) mit Tonhoehenverlauf
        self._tone_db = _cdb(c.PFIFF_MIN_DB)
        self._tn = 0                # Tonmessungen in der laufenden Folge
        self._tn_last = 0
        self._fmin = 0
        self._fmax = 0
        self._pfiff_until = 0
        self._pfiff_lock = 0
        self._stats_reset()

    # ── Statistik fuer das Logfile ────────────────────────────
    def _stats_reset(self):
        self.n_startle = 0
        self.n_wake = 0
        self.n_pfiff = 0            # erkannte Pfiffe
        self.n_ton = 0              # Tonmessungen (auch ohne Pfiff: Piepen u. ae.)
        self.listen_ms = 0
        self.annoy_ms = 0
        self.base_lo = None
        self.base_hi = None
        self.peak = None
        self.mic_ms = 0

    def pop_stats(self):
        """(Knaller, Nacht-Weckrufe, Zuhoer-s, Genervt-s, Grundrauschen min,
        max, Spitze in dBFS, laengste Mikrofonmessung in ms, Pfiffe,
        Tonmessungen) - und zuruecksetzen."""
        def f(v):
            return None if v is None else v / 100
        out = (self.n_startle, self.n_wake, self.listen_ms // 1000,
               self.annoy_ms // 1000, f(self.base_lo), f(self.base_hi),
               f(self.peak), self.mic_ms, self.n_pfiff, self.n_ton)
        self._stats_reset()
        return out

    def take_wake(self):
        w = self._wake
        self._wake = False
        return w

    # ── Auswertung ────────────────────────────────────────────
    def update(self, db, now, dur_ms=0, sleeping=False, hz=0):
        """Nach jeder Pegelmessung aufrufen. dur_ms = Dauer der Messung,
        hz = Frequenz eines reinen Tons im Burst (Microphone.tone_hz) oder 0."""
        d = _cdb(db)
        if self.base is None:
            self.base = max(self._lo, min(self._hi, d))
            self._prev = d
            self._t = now
        dt = time.ticks_diff(now, self._t)
        self._t = now
        if dt < 0 or dt > 2000:
            dt = 0                                  # Pause (z. B. Datenansicht)

        # Grundrauschen: sofort runter, langsam hoch
        base = self.base
        if d < base:
            base = max(self._lo, base - max(1, (base - d) >> 2))   # schnell, aber nicht auf jede Spitze nach unten
            self._acc = 0
        elif d > base:
            self._acc += dt * (self._rise_q if d - base < 300 else self._rise_l)
            if self._acc >= 60000:
                step = self._acc // 60000
                self._acc -= step * 60000
                base = min(base + step, d, self._hi)
        self.base = base

        delta = d - base
        jump = d - self._prev
        self._prev = d
        a, b = self._d1, self._d2
        med = max(min(delta, a), min(max(delta, a), b))   # Median aus 3
        self._d2, self._d1 = a, delta

        if dur_ms > self.mic_ms:
            self.mic_ms = dur_ms
        if self.peak is None or d > self.peak:
            self.peak = d
        if self.base_lo is None or base < self.base_lo:
            self.base_lo = base
        if self.base_hi is None or base > self.base_hi:
            self.base_hi = base

        locked = time.ticks_diff(self._lock, now) > 0

        tonal = hz > 0 and delta >= self._tone_db        # reiner Ton, deutlich ueber dem Grund

        if sleeping:
            self.state = ""
            self._listen = False
            self._tn = 0
            if not locked and delta >= self._wake_db and jump >= self._jump:
                self._wake = True
                self._lock = time.ticks_add(now, config.EARS_LOCK_MS)
                self.n_wake += 1
            return

        # Pfiff: mehrere reine Tonmessungen hintereinander, Tonhoehe aendert sich
        if tonal:
            self.n_ton += 1
            if self._tn == 0 or time.ticks_diff(now, self._tn_last) > config.PFIFF_GAP_MS:
                self._tn = 1
                self._fmin = self._fmax = hz
            else:
                self._tn += 1
                if hz < self._fmin:
                    self._fmin = hz
                if hz > self._fmax:
                    self._fmax = hz
            self._tn_last = now
            if config.PFIFF_DEBUG:
                print("Ton %d Hz  +%.1f dB  Folge %d  (%d..%d Hz)" % (
                    hz, delta / 100, self._tn, self._fmin, self._fmax))
            if (self._tn >= config.PFIFF_MIN_READS
                    and time.ticks_diff(self._pfiff_lock, now) <= 0
                    and self._fmax * 100 >= self._fmin * (100 + config.PFIFF_GLIDE_PCT)):
                self._pfiff_until = time.ticks_add(now, config.PFIFF_MS)
                self._pfiff_lock = time.ticks_add(now, config.PFIFF_MS + config.PFIFF_LOCK_MS)
                self._listen = False
                self._startle_until = now
                self._tn = 0
                self.n_pfiff += 1
                if config.PFIFF_DEBUG:
                    print("Pfiff erkannt")
        if time.ticks_diff(self._pfiff_until, now) > 0:
            self.state = "pfiff"
            return

        # Knall: Schwelle ueberschritten UND steile Flanke (kein Dauerlaerm);
        # ein reiner Ton ist kein Knall (Pfiff-Beginn)
        if not locked and not tonal and delta >= self._startle and jump >= self._jump:
            self._startle_until = time.ticks_add(now, config.EARS_STARTLE_MS)
            self._lock = time.ticks_add(now, config.EARS_LOCK_MS)
            self._listen = False
            self.n_startle += 1
            locked = True
        if time.ticks_diff(self._startle_until, now) > 0:
            self.state = "startle"
            return

        # Zuhoeren / Genervt: Hysterese plus Nachlauf, damit Sprechpausen
        # den Zustand nicht zerhacken
        if med >= self._on and not locked and not self._listen:
            self._listen = True
            self._loud_since = now
        if med >= self._off:
            self._last_loud = now
        elif self._listen and time.ticks_diff(now, self._last_loud) >= config.EARS_HANG_MS:
            self._listen = False

        age = time.ticks_diff(now, self._loud_since)
        if not self._listen:
            self.state = ""
        elif age >= config.EARS_ANNOY_MS + config.EARS_ANNOY_MAX_MS:
            self.state = ""                 # aufgegeben: Dauerlaerm wird hingenommen
        elif age >= config.EARS_ANNOY_MS:
            self.state = "annoyed"
            self.annoy_ms += dt
        else:
            self.state = "listen"
            self.listen_ms += dt

# EOF 2026-11-15
