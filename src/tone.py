# tone.py
# Ton-Erkennung fuer den Pfiff (Cat-Call): findet in einem Mikrofon-Burst
# einen reinen, einzelnen Ton und liefert dessen Frequenz in Hz (sonst 0).
#
# Verfahren (reine Ganzzahlen, keine Heap-Objekte pro Aufruf):
#   1. Frequenz aus den Nulldurchgaengen (mit Hysterese gegen Rauschen), nur
#      ueber die Spanne zwischen erstem und letztem Durchgang:
#        f = (Durchgaenge - 1) / 2 / Dauer dieser Spanne
#      Die Abtastrate muss man dazu nicht kennen - die Burstdauer reicht. Das
#      ist wichtig, weil die Python-Abtastschleife je nach WLAN-Last 16 bis
#      36 kHz schafft (siehe mic_ms im Log).
#   2. Reinheit: normierte Autokorrelation bei einer Periode Abstand. Ein
#      Pfeifton liegt bei ~1, Sprache, Musik, Rauschen, Klatschen deutlich
#      darunter.
# Simulation am Rechner (Pfiff, Sprache, TV, Rauschen, Klatschen, Tuer, Piepen):
# alle Pfiffe erkannt, Sprache/TV/Rauschen/Knaelle 0 Treffer.
#
# Die beiden Rechenschleifen laufen als @micropython.viper (~1 ms statt ~25 ms
# in normalem Python). Ohne MicroPython (Test am PC) gibt es reine Python-
# Fassungen mit identischem Ergebnis.

try:
    import micropython

    @micropython.viper
    def _zc(buf: ptr16, n: int, mean: int, hyst: int) -> int:
        # Rueckgabe gepackt: Anzahl | erster Index << 10 | letzter Index << 20
        zc = 0
        st = 0
        first = 0
        last = 0
        for i in range(n):
            d = int(buf[i]) - mean
            if d > hyst:
                if st < 0:
                    if zc == 0:
                        first = i
                    last = i
                    zc += 1
                st = 1
            elif d < 0 - hyst:
                if st > 0:
                    if zc == 0:
                        first = i
                    last = i
                    zc += 1
                st = -1
        return zc | (first << 10) | (last << 20)

    @micropython.viper
    def _corr(buf: ptr16, n: int, mean: int, lag: int) -> int:
        # Werte auf +-1400 begrenzt: 512 * 1400^2 = 1,0e9 passt in 31 Bit
        acc = 0
        for i in range(n - lag):
            a = int(buf[i]) - mean
            b = int(buf[i + lag]) - mean
            if a > 1400:
                a = 1400
            if a < -1400:
                a = -1400
            if b > 1400:
                b = 1400
            if b < -1400:
                b = -1400
            acc += a * b
        return acc

except ImportError:                      # PC-Test ohne MicroPython
    def _zc(buf, n, mean, hyst):
        zc = 0
        st = 0
        first = 0
        last = 0
        for i in range(n):
            d = int(buf[i]) - mean
            if d > hyst:
                if st < 0:
                    if zc == 0:
                        first = i
                    last = i
                    zc += 1
                st = 1
            elif d < -hyst:
                if st > 0:
                    if zc == 0:
                        first = i
                    last = i
                    zc += 1
                st = -1
        return zc | (first << 10) | (last << 20)

    def _corr(buf, n, mean, lag):
        acc = 0
        for i in range(n - lag):
            a = max(-1400, min(1400, int(buf[i]) - mean))
            b = max(-1400, min(1400, int(buf[i + lag]) - mean))
            acc += a * b
        return acc


def tone_hz(buf, n, mean, rms, dur_us, f_min, f_max, corr_pct):
    """Frequenz (Hz) des reinen Tons im Burst oder 0.
    buf = array('H') der ADC-Werte, mean = Mittelwert, rms = Effektivwert in
    ADC-Stufen, dur_us = Dauer der Aufnahme."""
    if dur_us <= 0:
        return 0
    hyst = int(rms) >> 2
    if hyst < 2:
        hyst = 2
    p = _zc(buf, n, mean, hyst)
    zc = p & 1023
    first = (p >> 10) & 1023
    last = (p >> 20) & 1023
    span = last - first                    # Abtastwerte zwischen erstem und letztem Durchgang
    if zc < 5 or span <= 0:
        return 0
    # Nur die Spanne mit Ton zaehlt: ein Burst, in dem der Ton erst spaet
    # beginnt oder frueh endet, darf die Frequenz nicht nach unten verfaelschen.
    hz = (zc - 1) * n * 500000 // (span * dur_us)
    if hz < f_min or hz > f_max:
        return 0
    lag = 2 * span // (zc - 1)             # eine Periode in Abtastwerten
    e0 = _corr(buf, n, mean, 0)
    if e0 <= 0:
        return 0
    best = 0
    for lg in (lag - 1, lag, lag + 1):
        if lg < 2 or lg > n // 2:
            continue
        c = _corr(buf, n, mean, lg)
        # auf gleiche Ueberlappung umrechnen: c * n / (n - lg)
        c = c * n // (n - lg)
        if c > best:
            best = c
    return hz if best * 100 >= corr_pct * e0 else 0

# EOF 2026-11-18
