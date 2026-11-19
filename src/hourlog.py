# hourlog.py
# Stuendliches Betriebslog als CSV im Flash des Pico (config.LOG_FILE).
# Pro Stunde genau eine Zeile mit Mittel-/Extremwerten - kein Messwert-
# Strom. Das schont den Flash (24 Schreibzugriffe pro Tag, ~2 kB/Tag) und den
# Heap (nur ein paar Zaehler, kein Puffer).
#
# Zeitstempel = Beginn des Zeitraums in Ortszeit (braucht NTP). Ohne Uhrzeit
# wird nach je 60 Minuten Laufzeit geschrieben und "-" eingetragen.
# Nach jedem Start folgt eine Zeile "# Start;<Reset-Grund>;<Ortszeit>;nach N s".
# Sie wird erst nach dem ersten Zeitabgleich geschrieben (meist wenige
# Sekunden nach dem Start); ohne Uhrzeit nach spaetestens _START_WAIT_MS mit "-".
#
# Groesse: Ab LOG_MAX_BYTES wird log.csv zu log.csv.old (die aeltere .old
# faellt weg). Zwei Dateien = ca. 3-4 Wochen Verlauf.
#
# Spalten (Trennzeichen ;):
#   ab       Beginn des Zeitraums
#   n        Anzahl Sensormessungen (3 s) im Zeitraum
#   temp, hum, hpa, lux, iaq   Mittelwerte (iaq = Score 0..1)
#   base_lo, base_hi           Grundrauschen min/max (dBFS)
#   peak                       lauteste Einzelmessung (dBFS)
#   knall, nacht               erkannte Knaller / Nacht-Weckrufe
#   zuhoer_s, genervt_s        Sekunden in diesen Zustaenden
#   ram_min, block_min         kleinster freier RAM / groesster Block (kB)
#   mic_ms                     laengste Mikrofonmessung
#   loop_max, ruckler          laengster Schleifendurchlauf (ms), Anzahl > 250 ms
#   augen_pct                  Anteil Augen-Modus (%)
#   wlan                       WLAN am Zeilenende verbunden (1/0)
#   pfiff, ton                 erkannte Pfiffe / Tonmessungen (reine Toene, z. B. Piepen)

import os
import time

_HEADER = ("ab;n;temp;hum;hpa;lux;iaq;base_lo;base_hi;peak;knall;nacht;"
           "zuhoer_s;genervt_s;ram_min;block_min;mic_ms;loop_max;ruckler;"
           "augen_pct;wlan;pfiff;ton\n")
_SLOW_MS = 250
_START_WAIT_MS = 60000   # so lange auf die Uhrzeit fuer die Startzeile warten


def _fmt(v, f):
    return "" if v is None else f.format(v)


class HourLog:
    def __init__(self, path, max_bytes, reset_cause=""):
        self.path = path
        self.max_bytes = max_bytes
        self._label = "-"
        self._hour = None
        self._t_start = time.ticks_ms()
        self._t_boot = self._t_start
        self._start = str(reset_cause)   # Startzeile folgt in tick(), sobald die Uhrzeit da ist
        self._clear()
        try:                                # Spalten geaendert: alte Datei nach .old, neu beginnen
            with open(path) as f:
                first = f.readline()
            if first != _HEADER:
                self._rotate()
        except OSError:
            pass

    def _clear(self):
        self._n = 0
        self._sum = [0.0, 0.0, 0.0, 0.0, 0.0]      # temp, hum, hpa, lux, iaq
        self._cnt = [0, 0, 0, 0, 0]
        self._ram = None
        self._blk = None
        self._loop_max = 0
        self._slow = 0
        self._ms = 0
        self._eyes_ms = 0

    # ── Datensammlung (billig, laeuft staendig) ───────────────
    def add_climate(self, temp, hum, hpa, lux, iaq):
        self._n += 1
        for i, v in enumerate((temp, hum, hpa, lux, iaq)):
            if v is not None:
                self._sum[i] += v
                self._cnt[i] += 1

    def add_mem(self, free, block):
        if self._ram is None or free < self._ram:
            self._ram = free
        if block is not None and (self._blk is None or block < self._blk):
            self._blk = block

    def note_loop(self, lap_ms, eyes):
        if lap_ms > self._loop_max:
            self._loop_max = lap_ms
        if lap_ms > _SLOW_MS:
            self._slow += 1
        if 0 <= lap_ms < 5000:              # NTP/WLAN-Verbindungsaufbau nicht mitzaehlen
            self._ms += lap_ms
            if eyes:
                self._eyes_ms += lap_ms

    # ── Schreiben ─────────────────────────────────────────────
    def tick(self, now, lt, ears, connected):
        """Etwa einmal pro Sekunde aufrufen. lt = Ortszeit-Tupel oder None."""
        if self._start is not None:
            waited = time.ticks_diff(now, self._t_boot)
            if lt is not None or waited >= _START_WAIT_MS:
                stamp = "%04d-%02d-%02d %02d:%02d:%02d" % lt[:6] if lt else "-"
                self._line("# Start;%s;%s;nach %d s\n" % (self._start, stamp, waited // 1000))
                self._start = None
        if lt is not None:
            if self._hour is None:
                self._hour = lt[3]
                self._label = "%04d-%02d-%02d %02d:%02d" % lt[:5]
            elif lt[3] != self._hour:
                self._write(ears, connected)
                self._hour = lt[3]
                self._label = "%04d-%02d-%02d %02d:%02d" % lt[:5]
        elif time.ticks_diff(now, self._t_start) >= 3600000:
            self._write(ears, connected)
            self._t_start = now

    def _avg(self, i, f):
        return f.format(self._sum[i] / self._cnt[i]) if self._cnt[i] else ""

    def _write(self, ears, connected):
        kn, wk, ls, an, lo, hi, pk, mic, pf, tn = ears.pop_stats()
        pct = (100 * self._eyes_ms // self._ms) if self._ms else 0
        row = ";".join((
            self._label, str(self._n),
            self._avg(0, "{:.1f}"), self._avg(1, "{:.0f}"), self._avg(2, "{:.1f}"),
            self._avg(3, "{:.0f}"), self._avg(4, "{:.2f}"),
            _fmt(lo, "{:.1f}"), _fmt(hi, "{:.1f}"), _fmt(pk, "{:.1f}"),
            str(kn), str(wk), str(ls), str(an),
            _fmt(None if self._ram is None else self._ram / 1024, "{:.1f}"),
            _fmt(None if self._blk is None else self._blk / 1024, "{:.1f}"),
            str(mic), str(self._loop_max), str(self._slow), str(pct),
            "1" if connected else "0", str(pf), str(tn))) + "\n"
        self._clear()
        self._line(row)

    def _rotate(self):
        try:
            os.remove(self.path + ".old")
        except OSError:
            pass
        os.rename(self.path, self.path + ".old")

    def _line(self, text):
        """Eine Zeile anhaengen; Fehler (Flash voll o. ae.) duerfen den
        Hauptlauf nie stoeren."""
        try:
            try:
                size = os.stat(self.path)[6]
            except OSError:
                size = -1
            if size > self.max_bytes:
                self._rotate()
                size = -1
            with open(self.path, "a") as f:
                if size < 0:
                    f.write(_HEADER)
                f.write(text)
        except Exception as error:
            print("Log:", error)

# EOF 2026-11-19
