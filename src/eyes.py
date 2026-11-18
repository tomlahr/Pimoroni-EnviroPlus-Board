# eyes.py
# Bildschirmschoner "Augen" fuer das Enviro+ (240 x 240): zwei Comic-Augen
# (weisse Ovale, schwarze Pupillen mit Glanzpunkt) nach einem Video-Vorbild.
#
#   Kontur (2 px) - Farbe der Luftqualitaet, bleibt immer sichtbar
#   Fuellung      - Weiss, Pupillen und Lider; nur sie aendern sich
#
#   gut           gruen, offen, Pupillen schauen umher, zwinkern gelegentlich
#   maessig       gelb, Oberlid halb geschlossen, skeptisch (rechts tiefer)
#   schlecht      rot, grimmig (Lider innen tiefer), Unterlid kneift
#   Aufwaermphase cyan, verschlafen, Blick nach unten, langsames Blinzeln
#
# Die Ovale stehen still, nur die Pupillen wandern. Beim Blinzeln faehrt das
# Oberlid ueber das Weiss; die Kontur bleibt stehen.
#
# Speicher: Kontur und weisse Flaeche werden einmal berechnet. Pro Bild
# entstehen nur dann neue Punktlisten, wenn ein Lid sichtbar ist - bei
# offenen Augen praktisch kein Speichermuell (wichtig fuer den knappen Heap).
#
# Lider: Die Lidflaeche entsteht aus den Ovalpunkten - die Punkte der einen
# Ovalhaelfte bleiben, die der anderen werden senkrecht auf die Lidlinie
# geschoben, begrenzt auf den Ovalrand an derselben Stelle. Die Flaeche
# liegt dadurch immer innerhalb des Ovals und beruehrt die Kontur nicht.
#
# Blinzeln ("Datas Fourier-Algorithmus"): Der Abstand bis zum naechsten
# Lidschlag ergibt sich aus drei ueberlagerten Sinuswellen mit unrunden
# Perioden plus Zufall - das Muster wiederholt sich praktisch nie. Dazu
# gelegentliches Doppelblinzeln und bei guter Luft ab und zu ein Zwinkern.
#
# Schlafmodus (draw(..., sleeping=True), per config.SLEEP_FROM/UNTIL):
# Die Lider schliessen sich langsam (~5 s) bis auf einen schmalen Streifen,
# der leicht "atmet"; ab und zu steigt ein "z Z Z" treppenfoermig auf (jeder
# Buchstabe groesser als der vorige). Blinzeln und Umherschauen ruhen. Beim
# Aufwachen oeffnen sich die Lider ebenso langsam. peek() oeffnet kurz ein
# Auge (Geraeusch in der Nacht), dann geht es weiter mit Schlafen.
#
# Brauen und Mund (optional, face.py): attach_face() haengt sie an; sie folgen
# denselben Stimmungsschluesseln. Gaehnen und Kuss schliessen die Lider ueber
# face.lid, waehrenddessen kein Blinzeln.
#
# Geraeuschreaktion (draw(..., ear=...), Zustand aus ears.py): "listen",
# "startle", "annoyed" und "pfiff" ueberschreiben die Stimmung der Luftqualitaet fuer
# die Lider und den Blick; die Konturfarbe bleibt die der Luftqualitaet.
#
# Bildrate: Der ST7789-Treiber kennt kein Teil-Update (partial_update() ist
# dort leer), jedes Bild ist ein Vollbild mit ~45 ms. Deshalb ein Bild alle
# EYES_FRAME_MS (80 ms = 12,5 Bilder/s); die Hauptschleife bleibt frei.

import math
import random
import time

_CX = (77, 163)     # Augenmitten (links, rechts) - schmaler Spalt wie im Vorbild
_CY = 120
_HW = 40            # halbe Breite des weissen Ovals
_HH = 56            # halbe Hoehe des weissen Ovals
_LINE = 2           # Konturstaerke
_PR = 14            # Pupillenradius
_GR = 4             # Glanzpunkt-Radius
# Pupillen-Bewegungsraum (Ellipse), damit die Pupille im Weiss bleibt
_PX = _HW - _PR - 3
_PY = _HH - _PR - 3
_N = 36             # Polygonpunkte pro Oval
_UNIT = [(math.cos(2 * math.pi * k / _N), math.sin(2 * math.pi * k / _N))
         for k in range(_N)]

# Stimmungen: lid = Oberlid (Anteil der Augenhoehe), tilt = Schraege
# (+ = innen tiefer/grimmig, - = aussen tiefer/muede), bot = Unterlid
# (Kneifen), skew = Zusatz-Oberlid rechts (skeptisch), look = Blickradius
# 0..1, gy = Blick nach unten (Pixel), sac = Sakkaden-Abstand s (min, max),
# blink = mittlerer Blinzelabstand s, wink = Zwinkern, slow = langsam.
_MOODS = {
    "green":  dict(lid=0.00, tilt=0.00, bot=0.00, skew=0.00, pr=14,
                   look=1.0, gy=0, sac=(1.2, 3.5), blink=3.5, wink=True, slow=False),
    "yellow": dict(lid=0.33, tilt=-0.06, bot=0.00, skew=0.16, pr=14,
                   look=0.7, gy=0, sac=(2.0, 5.0), blink=4.0, wink=False, slow=False),
    "red":    dict(lid=0.30, tilt=0.26, bot=0.22, skew=0.00, pr=14,
                   look=0.9, gy=6, sac=(0.6, 1.8), blink=2.5, wink=False, slow=False),
    "grey":   dict(lid=0.52, tilt=-0.14, bot=0.00, skew=0.00, pr=14,
                   look=0.5, gy=14, sac=(4.0, 8.0), blink=5.0, wink=False, slow=True),
    # Geraeuschreaktion (pr = Pupillenradius, ease = Ueberblendung pro Bild)
    # listen:  Lider ganz auf, Pupillen etwas groesser, Blick ruhig und mittig
    # startle: schlagartig weit auf, Pupillen klein, Blick starr; danach Blinzeln
    # annoyed: Lider halb, flacher Blick, Pupillen huschen unruhig
    "listen":  dict(lid=0.00, tilt=0.00, bot=0.00, skew=0.00, pr=16, ease=0.25,
                    look=0.35, gy=0, sac=(2.5, 5.0), blink=6.0, wink=False, slow=False),
    "startle": dict(lid=0.00, tilt=0.00, bot=0.00, skew=0.00, pr=8, ease=0.80,
                    look=0.0, gy=0, sac=(1.5, 2.5), blink=5.0, wink=False, slow=False),
    "annoyed": dict(lid=0.45, tilt=0.04, bot=0.00, skew=0.00, pr=14, ease=0.20,
                    look=1.0, gy=4, sac=(0.4, 1.0), blink=3.0, wink=False, slow=False),
    # pfiff: verliebt - Blick ruhig nach vorn, sanft; mit face.py Herzpupillen
    "pfiff":   dict(lid=0.00, tilt=-0.05, bot=0.00, skew=0.00, pr=15, ease=0.40,
                    look=0.15, gy=0, sac=(2.5, 4.0), blink=6.0, wink=False, slow=False),
}

# Lidoeffnung pro Bild (80 ms): 1 = offen, 0 = zu
_BLINK = (0.50, 0.10, 0.00, 0.40, 1.0)
_BLINK_SLOW = (0.70, 0.45, 0.20, 0.05, 0.00, 0.00, 0.25, 0.55, 0.80, 1.0)
_WINK = (0.50, 0.10, 0.00, 0.00, 0.00, 0.40, 1.0)

_MOOD_EASE = 0.15   # Ueberblendung der Stimmung pro Bild (~1 s)
_GAZE_EASE = 0.45   # Blicksprung pro Bild (~3 Bilder)

_SLEEP_EASE = 0.05      # Einschlafen/Aufwachen pro Bild (~5 s)
_SLEEP_OPEN = 0.06      # Lidoeffnung im Schlaf (schmaler Streifen)
_SLEEP_BREATH = 0.03    # "Atmen" um diesen Wert
_SLEEP_BREATH_S = 6.0   # Atemperiode in s
_PEEK_MS = 2500         # Dauer des Nacht-Blicks (ein Auge oeffnet kurz)
_PEEK_OPEN = 0.45       # Lidoeffnung dabei
_Z_CYCLE_MS = 8000      # "z Z Z" alle 8 s
_Z_STEP_MS = 1200       # Abstand zwischen den drei Buchstaben
_Z_HOLD_MS = 5600       # ab hier verschwinden alle drei
# Buchstabe, Schriftgroesse, Lage (x, y) - treppenfoermig aufsteigend, wachsend
_Z_LETTERS = (("z", 2, 184, 44), ("Z", 3, 198, 22), ("Z", 4, 212, 0))


def _rnd():
    return random.getrandbits(16) / 65535


def _oval(cx, cy, hw, hh):
    return [(cx + int(hw * c), cy + int(hh * s)) for c, s in _UNIT]


class Eyes:
    def __init__(self):
        # Statische Formen: Kontur (farbig, groesser) und weisse Flaeche
        self._ring = [_oval(cx, _CY, _HW + _LINE, _HH + _LINE) for cx in _CX]
        self._white = [_oval(cx, _CY, _HW, _HH) for cx in _CX]
        self._p = {k: _MOODS["grey"][k] for k in ("lid", "tilt", "bot", "skew", "pr")}
        self._mood = "grey"
        self._gx = self._gy = 0.0           # aktueller Blick (Pupillenversatz)
        self._tx = self._ty = 0.0           # Blickziel
        self._t0 = time.ticks_ms()
        self._t_sac = 0
        self._t_blink = 0
        self._seq = None                    # laufende Lidsequenz
        self._seq_i = 0
        self._wink_eye = -1                 # -1 = beide Augen, 0/1 = ein Auge
        self._double = False
        self._sleep = 0.0                   # 0 = wach ... 1 = schlaeft
        self._t_z = 0
        self._ear = ""                      # Stimmungsschluessel der Geraeuschreaktion
        self._t_peek = time.ticks_add(self._t0, -_PEEK_MS - 1000)
        self._peek_eye = 0
        self._face = None                   # Brauen/Mund (face.py), optional
        self._minute = None                 # Minute des Tages (Ortszeit) oder None
        self.reset()

    def reset(self):
        """Beim Eintritt in den Bildschirmschoner: Augen offen, Blick mittig."""
        now = time.ticks_ms()
        self._gx = self._gy = self._tx = self._ty = 0.0
        self._seq = None
        self._t_sac = time.ticks_add(now, 1500)
        self._t_blink = time.ticks_add(now, 2000)

    def attach_face(self, face):
        self._face = face

    def set_minute(self, minute):
        self._minute = minute

    def peek(self):
        """Geraeusch in der Nacht: ein (zufaelliges) Auge oeffnet kurz.
        Wirkt nur, wenn die Augen schlafen."""
        if self._sleep > 0.5:
            self._t_peek = time.ticks_ms()
            self._peek_eye = int(_rnd() * 2) % 2

    def _peek_w(self, now):
        age = time.ticks_diff(now, self._t_peek)
        if age < 0 or age > _PEEK_MS:
            return 0.0
        if age < 300:
            return age / 300
        if age < 1500:
            return 1.0
        return 1.0 - (age - 1500) / (_PEEK_MS - 1500)

    # ── Verhalten ────────────────────────────────────────────
    def _next_blink_ms(self, base_s):
        t = time.ticks_diff(time.ticks_ms(), self._t0) / 1000
        f = (1 + 0.35 * math.sin(t / 11.3)
               + 0.20 * math.sin(t / 4.7 + 1.3)
               + 0.15 * math.sin(t / 2.9 + 0.4))
        f *= 0.75 + 0.5 * _rnd()
        return int(max(0.8, base_s * f) * 1000)

    def _start_blink(self, now, m):
        if self._double:
            self._double = False
            self._seq, self._wink_eye = _BLINK, -1
        elif m["wink"] and _rnd() < 0.12:
            self._seq, self._wink_eye = _WINK, int(_rnd() * 2) % 2
        else:
            self._seq = _BLINK_SLOW if m["slow"] else _BLINK
            self._wink_eye = -1
            self._double = not m["slow"] and _rnd() < 0.15
        self._seq_i = 0
        if self._double:
            self._t_blink = time.ticks_add(now, 250)
        else:
            self._t_blink = time.ticks_add(now, self._next_blink_ms(m["blink"]))

    def _start_saccade(self, now, m):
        if _rnd() < 0.2:
            tx, ty = 0.0, float(m["gy"])                     # zurueck zur Mitte
        else:
            tx = (_rnd() * 2 - 1) * _PX * m["look"]
            ty = (_rnd() * 2 - 1) * _PY * m["look"] + m["gy"]
        # auf den Bewegungsraum (Ellipse) begrenzen
        r = (tx / _PX) ** 2 + (ty / _PY) ** 2
        if r > 1:
            r = math.sqrt(r)
            tx, ty = tx / r, ty / r
        self._tx, self._ty = tx, ty
        lo, hi = m["sac"]
        self._t_sac = time.ticks_add(now, int((lo + (hi - lo) * _rnd()) * 1000))

    def _step(self, mood, sleeping, ear):
        now = time.ticks_ms()
        key = ear if ear and not sleeping else mood          # Geraeusch geht vor
        m = _MOODS.get(key, _MOODS["grey"])
        if key != self._mood:
            if self._mood == "startle":
                self._t_blink = now                          # nach dem Schreck: Blinzeln
            if key == "startle":
                self._seq = None                             # laufendes Blinzeln abbrechen
            self._mood = key
            self._t_sac = now                                # neuen Blick waehlen
        p = self._p
        ease = m.get("ease", _MOOD_EASE)
        for k in p:
            p[k] += (m[k] - p[k]) * ease

        self._sleep += ((1.0 if sleeping else 0.0) - self._sleep) * _SLEEP_EASE
        dozing = self._sleep > 0.5
        face = self._face
        if face is not None:
            face.step(now, key, dozing, self._minute, bool(ear) and not sleeping)
        if dozing:
            self._tx, self._ty = 0.0, _PY * 0.5              # Blick ruht, leicht nach unten
            self._seq = None
            self._t_sac = time.ticks_add(now, 1500)          # nach dem Aufwachen kurz ruhig
            self._t_blink = time.ticks_add(now, 2000)
        elif time.ticks_diff(now, self._t_sac) >= 0:
            self._start_saccade(now, m)
        self._gx += (self._tx - self._gx) * _GAZE_EASE
        self._gy += (self._ty - self._gy) * _GAZE_EASE

        if (not dozing and self._seq is None and key != "startle"
                and not (face is not None and face.busy)
                and time.ticks_diff(now, self._t_blink) >= 0):
            self._start_blink(now, m)
        openness = [1.0, 1.0]
        if self._seq is not None:
            v = self._seq[self._seq_i]
            if self._wink_eye < 0:
                openness = [v, v]
            else:
                openness[self._wink_eye] = v
                openness[1 - self._wink_eye] = 0.85      # anderes Auge kneift leicht
            self._seq_i += 1
            if self._seq_i >= len(self._seq):
                self._seq = None
        if face is not None and face.lid > 0.01:
            lim = 1.0 - face.lid                          # Gaehnen/Kuss: Lider sinken
            openness = [o if o < lim else lim for o in openness]
        if self._sleep > 0.01:
            t = time.ticks_diff(now, self._t0) / 1000
            closed = _SLEEP_OPEN + _SLEEP_BREATH * math.sin(2 * math.pi * t / _SLEEP_BREATH_S)
            s = self._sleep
            w = self._peek_w(now)
            if w > 0:
                # das gewaehlte Auge oeffnet sich, das andere bleibt zu
                peek = closed + (_PEEK_OPEN - closed) * w
                cl = [closed, closed]
                cl[self._peek_eye] = peek
            else:
                cl = (closed, closed)
            openness = [openness[i] * (1 - s) + cl[i] * s for i in (0, 1)]
        return openness

    # ── Zeichnen ─────────────────────────────────────────────
    def draw(self, g, bg_pen, white_pen, line_pen, mood, sleeping=False, ear="", face_pens=None):
        """Ein Bild in den Framebuffer zeichnen. update() macht der Aufrufer.
        ear = Zustand der Geraeuschreaktion ("", "listen", "startle", "annoyed")."""
        openness = self._step(mood, sleeping, ear)
        p = self._p
        g.set_pen(bg_pen)
        g.clear()
        px, py = int(self._gx), int(self._gy)
        pr = int(p["pr"] + 0.5)
        face = self._face if face_pens is not None else None
        heart = face is not None and face.heart_eyes
        now = time.ticks_ms()
        for i in (0, 1):
            cx = _CX[i]
            g.set_pen(line_pen)
            g.polygon(self._ring[i])
            g.set_pen(white_pen)
            g.polygon(self._white[i])
            if heart:                                       # Pfiff: Herz statt Pupille
                face.pupil_heart(g, face_pens[2], cx + px, _CY + py, now)
            else:
                g.set_pen(bg_pen)
                g.circle(cx + px, _CY + py, pr)
            g.set_pen(white_pen)
            g.circle(cx + px + 5, _CY + py - 6, _GR)
            self._lids(g, i, cx, openness[i], p, bg_pen, line_pen)
        if face is not None:
            face.draw(g, face_pens + (bg_pen,), now)
        if self._sleep > 0.9:
            self._zzz(g, line_pen)

    def _zzz(self, g, pen):
        """"z Z Z" steigt ueber dem rechten Auge treppenfoermig auf: die drei
        Buchstaben erscheinen nacheinander (jeder groesser und weiter oben),
        bleiben kurz stehen und verschwinden gemeinsam; dann Pause."""
        now = time.ticks_ms()
        age = time.ticks_diff(now, self._t_z)
        if age < 0 or age > _Z_CYCLE_MS:
            self._t_z = now
            age = 0
        if age > _Z_HOLD_MS:
            return
        g.set_pen(pen)
        for k, (ch, scale, x, y) in enumerate(_Z_LETTERS):
            if age >= k * _Z_STEP_MS:
                g.text(ch, x, y, -1, scale)

    def _lids(self, g, i, cx, op, p, bg_pen, line_pen):
        top = _CY - _HH
        h = 2 * _HH
        lid = p["lid"] + (p["skew"] if i == 1 else 0.0)
        lid += (1.0 - lid) * (1.0 - op)                     # Blinzeln: Lid faehrt herunter
        tilt = p["tilt"] * op
        inner = max(0.0, min(1.0, lid + tilt))
        outer = max(0.0, min(1.0, lid - tilt))
        if inner > 0.01 or outer > 0.01:
            # Innenseite: beim linken Auge rechts, beim rechten Auge links
            yl = top + (outer if i == 0 else inner) * h
            yr = top + (inner if i == 0 else outer) * h
            k = (yr - yl) / (2 * _HW)
            x0 = cx - _HW
            g.set_pen(bg_pen)
            # oberer Ovalrand bleibt, unterer wandert zur Lidlinie (nicht ueber den Rand)
            g.polygon([(x, y if y <= _CY else max(2 * _CY - y, min(y, int(yl + k * (x - x0)))))
                       for x, y in self._white[i]])
            Eyes._edge(g, cx, line_pen, lambda x: yl + k * (x - x0))
        bot = p["bot"] * op
        if bot > 0.02:
            rad = 3 * _HW
            yc = _CY + _HH + rad - bot * h
            g.set_pen(bg_pen)
            # unterer Ovalrand bleibt, oberer wandert zur Unterlid-Kante
            g.polygon([(x, y if y >= _CY else min(2 * _CY - y,
                        max(y, int(yc - math.sqrt(rad * rad - (x - cx) ** 2)))))
                       for x, y in self._white[i]])
            Eyes._edge(g, cx, line_pen, lambda x: yc - math.sqrt(rad * rad - (x - cx) ** 2))

    @staticmethod
    def _edge(g, cx, pen, f):
        """Lidkante als 2-px-Linie, nur innerhalb des weissen Ovals."""
        g.set_pen(pen)
        last = None
        for k in range(13):
            x = cx - _HW + 2 * _HW * k / 12
            q = 1 - ((x - cx) / _HW) ** 2
            y = f(x)
            if q > 0 and abs(y - _CY) <= _HH * math.sqrt(q):
                pt = (int(x), int(y))
                if last is not None:
                    g.line(last[0], last[1], pt[0], pt[1])
                    g.line(last[0], last[1] + 1, pt[0], pt[1] + 1)
                last = pt
            else:
                last = None

# EOF 2026-11-18
