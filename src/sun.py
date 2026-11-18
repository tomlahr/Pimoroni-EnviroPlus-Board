# sun.py
# Farbe des Augenweiss nach Tageszeit, synchron zu Sonnenauf- und -untergang.
#
# Sonnenzeiten: NOAA-Naeherung (Genauigkeit ~1-2 min), lokal aus Datum,
# Breite/Laenge (config.LATITUDE/LONGITUDE) und UTC-Versatz berechnet - kein
# Internet, kein Home Assistant noetig. Gerechnet wird einmal pro Tag.
#
# Drei Stufen, weich ineinander uebergeblendet (u = 0 .. 2):
#   0  Tag     helles Weiss                          (EYES_WHITE_DAY)
#   1  Abend   warmweiss, gedimmt                    (EYES_WHITE_EVENING)
#   2  Nacht   kleinste noch sichtbare Helligkeit    (EYES_WHITE_NIGHT)
#
# Ablauf:
#   Abend    beginnt EYES_TONE_SUN_MARGIN_MIN vor Sonnenuntergang, spaetestens
#            um EYES_TONE_EVENING_LATEST; Ueberblendung EYES_TONE_RAMP_MIN
#   Nacht    erreicht um EYES_TONE_NIGHT_AT (Ueberblendung 30 min davor),
#            gilt durch das Schlaffenster (ab SLEEP_FROM) bis SLEEP_UNTIL
#   Morgen   ab SLEEP_UNTIL 30 min zurueck auf Abend-Stufe, dann um den
#            Sonnenaufgang (+- Rand) auf Tag. Im Sommer (Aufgang vor dem
#            Aufwachen) direkt von Nacht auf Tag.
#
# Speicher: ein paar Floats einmal pro Tag, sonst nur Ganzzahlen.

import math

import config

_CUM = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)   # Tage vor Monatsbeginn


def sun_times(year, month, day, lat, lon, offset_min):
    """(Aufgang, Untergang) in Minuten nach Mitternacht Ortszeit.
    Polartag/-nacht: (None, None)."""
    yday = _CUM[month - 1] + day
    if month > 2 and year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
        yday += 1
    g = 2 * math.pi / 365 * (yday - 1)                 # Jahreswinkel (Mittag)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    c = (math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl))
         - math.tan(la) * math.tan(decl))
    if c < -1 or c > 1:
        return None, None
    ha = math.degrees(math.acos(c))
    rise = 720 - 4 * (lon + ha) - eqt + offset_min
    sset = 720 - 4 * (lon - ha) - eqt + offset_min
    return int(rise + 0.5), int(sset + 0.5)


def _hm(t):
    return t[0] * 60 + t[1]


def _ramp(m, a, b):
    """0 vor a, 1 ab b, linear dazwischen (in Tausendsteln, Ganzzahl)."""
    if m <= a:
        return 0
    if m >= b:
        return 1000
    return (m - a) * 1000 // (b - a)


def _mix(a, b, k):
    """Farbe a -> b, k in Tausendsteln."""
    return tuple(a[i] + (b[i] - a[i]) * k // 1000 for i in (0, 1, 2))


class EyeTone:
    def __init__(self):
        self._day = None
        self.rise = None                # Minuten nach Mitternacht (Ortszeit)
        self.set = None

    def level(self, minute):
        """Stufe in Tausendsteln: 0 = Tag, 1000 = Abend, 2000 = Nacht."""
        force = getattr(config, "EYES_TONE_FORCE", None)
        if force is not None:
            return int(force * 1000)
        c = config
        margin = c.EYES_TONE_SUN_MARGIN_MIN
        wake = _hm(c.SLEEP_UNTIL)
        night_at = _hm(c.EYES_TONE_NIGHT_AT)
        rise = self.rise if self.rise is not None else 7 * 60
        sset = self.set if self.set is not None else 17 * 60
        if minute < 720:
            u = 1000 - _ramp(minute, rise - margin, rise + margin)  # warm bis zum Aufgang
            n = 1000 - _ramp(minute, wake, wake + 30)              # Nacht bis zum Aufwachen
        else:
            start = min(sset - margin, _hm(c.EYES_TONE_EVENING_LATEST))
            u = _ramp(minute, start, start + c.EYES_TONE_RAMP_MIN)
            n = _ramp(minute, night_at - 30, night_at)
        return u + (2000 - u) * n // 1000

    def rgb(self, lt, offset_min):
        """Farbe des Augenweiss fuer das Ortszeit-Tupel lt."""
        day = (lt[0], lt[1], lt[2])
        if day != self._day:
            self._day = day
            try:
                self.rise, self.set = sun_times(lt[0], lt[1], lt[2], config.LATITUDE,
                                                config.LONGITUDE, offset_min)
            except Exception as error:
                print("Sonnenzeiten:", error)
                self.rise = self.set = None
        u = self.level(lt[3] * 60 + lt[4])
        c = config
        if u <= 1000:
            return _mix(c.EYES_WHITE_DAY, c.EYES_WHITE_EVENING, u)
        return _mix(c.EYES_WHITE_EVENING, c.EYES_WHITE_NIGHT, u - 1000)

# EOF 2026-11-18
