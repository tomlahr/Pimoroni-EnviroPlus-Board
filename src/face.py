# face.py
# Augenbrauen und Mund fuer den Augen-Bildschirmschoner (eyes.py), optional
# ueber config.EYES_FACE. Entwurf: Bilderstudie 2026-11-15.
#
#   Brauen  grau-weiss (Pen BROW), 7 px, Knick, Enden leicht gerundet
#   Mund    rot (Pen FACE_RED); Linie oder offen mit dunklem Innenraum; bei weit
#           offenem Mund eine rosa Zunge (Pen PINK); Herzen ebenfalls rosa
#   Alle drei Pens dimmt display.py mit dem Augenweiss (sun.py).
#
# Zustaende (Schluessel wie in eyes.py): green / yellow / red / grey (Luft),
# listen / startle / annoyed (Geraeusch), dazu "sleep". Jeder Zustand ist ein
# Satz Zielwerte; die aktuellen Werte laufen pro Bild ein Stueck dorthin
# (weiche Uebergaenge wie bei den Lidern).
#
# Animationen (Folgen aus Zustaenden, zufaellig, nur wenn nichts Lautes
# passiert):
#   Gaehnen  ab config.EYES_YAWN_FROM, ca. alle EYES_YAWN_MEAN_S s, ~3,7 s:
#            Lider sinken, Mund oeffnet weit, Brauen steigen innen
#   Kuss     abends bei guter Luft und Ruhe, ca. alle EYES_KISS_MEAN_S s, ~8,6 s:
#            Kussmund pulsiert dezent, kleine Herzen steigen auf
#   Pfiff    (ears.py "pfiff", Cat-Call): Herzen statt Pupillen (pulsieren),
#            Kussmund pulsiert, Herzen steigen links und rechts auf
# Dazu kleine Dauerbewegungen: beim Zuhoeren bewegt sich der Mund minimal
# ("Hmmm"), im Schlaf atmet der Mund.
#
# Speicher: Alle Zielwerte sind Konstanten. Die Umrisse (Brauen 10 Punkte,
# Mund ~26) werden nur neu berechnet, solange sich etwas bewegt (Uebergang,
# Zuhoeren, Atmen, Kuss-Puls) - im Ruhezustand wird die gemerkte Liste
# wiederverwendet, es entsteht kein Speichermuell. Geladen wird das Modul beim
# Start (display.load_face), nur wenn genug freier Heap da ist.

import math
import random
import time

import config

_CX = (77, 163)

_D = dict(boL=46, biL=46, boR=46, biR=46, ba=3, kf=0.5,
          w=80, cl=9, cr=9, qt=26, qb=26, A=0, dr=0, ym=210,
          rx=6, ry=4, ex=120, lid=0,
          kind=0, dim=0, solid=0, hide=0, ease=0.2)
_KEYS = ("boL", "biL", "boR", "biR", "ba", "kf", "w", "cl", "cr", "qt", "qb",
         "A", "dr", "ym", "rx", "ry", "ex", "lid")


def _t(**kw):
    d = dict(_D)
    d.update(kw)
    return d


# kind 0 = Linse (Linie/offener Mund), 1 = Ellipse; lid = Lidschluss 0..1
_T = {
    "green":   _t(dim=1),
    "yellow":  _t(boL=43, biL=39, boR=50, biR=52, w=48, cl=-3, cr=7, qt=0, qb=0),
    "red":     _t(boL=40, biL=63, boR=40, biR=63, ba=1, w=58, cl=-6, cr=-6, qt=-12, qb=-12),
    "grey":    _t(boL=55, biL=46, boR=55, biR=46, w=24, cl=0, cr=0, qt=-2, qb=10),
    "listen":  _t(boL=36, biL=33, boR=32, biR=36, kf=0.7, w=56, cl=-3, cr=2, qt=-2, qb=-2),
    "startle": _t(boL=30, biL=15, boR=15, biR=30, kf=0.7, w=54, cl=0, cr=0, qt=0, qb=0,
                  A=6, ym=212, ease=0.6),
    "annoyed": _t(boL=50, biL=55, boR=55, biR=50, ba=2, w=52, cl=0, cr=0, qt=0, qb=0,
                  A=3.5, dr=8, ym=208),
    "sleep":   _t(kind=1, rx=6, ry=4, ym=210, hide=1, ease=0.1),
    # Gaehnen
    "y0": _t(lid=0.3, w=40, cl=2, cr=2, qt=8, qb=8),
    "y1": _t(lid=0.5, boL=48, biL=44, boR=48, biR=44, kind=1, rx=14, ry=10, ym=206),
    "y2": _t(lid=0.72, boL=52, biL=41, boR=52, biR=41, kf=0.7, kind=1, rx=21, ry=25, ym=208),
    "y3": _t(lid=0.95, boL=52, biL=38, boR=52, biR=38, kf=0.7, kind=1, rx=22, ry=28, ym=208),
    "y4": _t(lid=0.6, boL=50, biL=44, boR=50, biR=44, kind=1, rx=14, ry=12, ym=207),
    "y5": _t(lid=0.3, w=44, cl=3, cr=3, qt=10, qb=10),
    # Kuss
    "k0": _t(lid=0.12, boL=44, biL=44, boR=44, biR=44, ba=4, kind=1, rx=6, ry=5,
             ex=118, ym=210, solid=1),
    "k1": _t(lid=0.18, boL=43, biL=43, boR=43, biR=43, ba=4, kind=1, rx=9, ry=8,
             ex=116, ym=210, solid=1),
    "k2": _t(lid=0.10, w=44, cl=6, cr=6, qt=14, qb=14, dim=1),
    # Pfiff: verliebt - Brauen hoch, Lider leicht gesenkt, Kussmund
    "pfiff": _t(lid=0.14, boL=36, biL=34, boR=36, biR=34, ba=4, kind=1, rx=10, ry=9,
                ex=116, ym=210, solid=1, ease=0.35),
}
_YAWN = ((600, "y0"), (500, "y1"), (600, "y2"), (800, "y3"), (500, "y4"), (700, "y5"))
_KISS = ((700, "k0"), (7000, "k1"), (900, "k2"))
_ANIM = ("listen", "sleep", "k1", "pfiff")     # Zustaende mit Dauerbewegung: jedes Bild neu

_BROW_X = ((-34, 30), (34, -30))     # (aussen, innen) relativ zur Augenmitte
_ELL = [(math.cos(2 * math.pi * k / 18), math.sin(2 * math.pi * k / 18)) for k in range(18)]
_N = 12                              # Stuetzstellen je Mundkurve
_STEP_MS = 5000                      # Zufallswuerfe fuer Gaehnen/Kuss alle 5 s


def _rnd():
    return random.getrandbits(16) / 65535


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


class Face:
    def __init__(self):
        self.cur = {k: float(_T["green"][k]) for k in _KEYS}
        self._tgt = _T["green"]
        self._name = "green"
        self.lid = 0.0                  # Lidschluss durch Gaehnen/Kuss (eyes.py liest das)
        self.busy = False               # Gaehnen/Kuss laeuft -> kein Blinzeln
        self._act = None
        self._act_i = 0
        self._act_t = 0
        self._act_kind = ""
        self._t_step = time.ticks_ms()
        self._t_ear = time.ticks_add(self._t_step, -120000)
        self._cool = {"yawn": self._t_step, "kiss": self._t_step}
        self._t0 = self._t_step
        self._tired = 0.0
        self._ops = []                  # gemerkte Zeichenbefehle (Rolle, Punkte)
        self._dirty = True

    # ── Ablauf ───────────────────────────────────────────────
    def _start(self, kind, now):
        self._act_kind = kind
        self._act = _YAWN if kind == "yawn" else _KISS
        self._act_i = 0
        self._act_t = time.ticks_add(now, self._act[0][0])
        self.busy = True

    def _stop(self, now):
        if self._act is not None:
            self._cool[self._act_kind] = now
        self._act = None
        self.busy = False

    @staticmethod
    def _minute_ok(minute, frm, until=None):
        if minute is None:
            return False
        a = frm[0] * 60 + frm[1]
        if until is None:
            return minute >= a
        b = until[0] * 60 + until[1]
        return a <= minute < b

    def step(self, now, key, dozing, minute, ear):
        """Einmal pro Bild. key = Stimmungsschluessel aus eyes.py, dozing = die
        Augen schlafen, minute = Minute des Tages (Ortszeit) oder None, ear =
        Geraeusch-Zustand aktiv."""
        if ear:
            self._t_ear = now
        # Abbruch bei Geraeusch oder Schlaf
        if self._act is not None and (ear or dozing):
            self._stop(now)
        # Weiterschalten der Folge
        if self._act is not None and time.ticks_diff(now, self._act_t) >= 0:
            self._act_i += 1
            if self._act_i >= len(self._act):
                self._stop(now)
            else:
                self._act_t = time.ticks_add(now, self._act[self._act_i][0])
        # Zufaellig neue Folge starten (alle 5 s ein Wurf)
        tired_changed = False
        if time.ticks_diff(now, self._t_step) >= _STEP_MS:
            self._t_step = now
            tired = 0.0 if minute is None else _clamp((minute - 1200) / 180, 0.0, 1.0)
            tired_changed = tired != self._tired
            self._tired = tired
            if self._act is None and not dozing and not ear and key in ("green", "yellow"):
                quiet = time.ticks_diff(now, self._t_ear) >= 60000
                if (self._minute_ok(minute, config.EYES_YAWN_FROM)
                        and time.ticks_diff(now, self._cool["yawn"]) > 120000
                        and _rnd() < _STEP_MS / 1000 / config.EYES_YAWN_MEAN_S):
                    self._start("yawn", now)
                elif (key == "green" and quiet
                        and self._minute_ok(minute, config.EYES_KISS_FROM, config.EYES_KISS_UNTIL)
                        and time.ticks_diff(now, self._cool["kiss"]) > 300000
                        and _rnd() < _STEP_MS / 1000 / config.EYES_KISS_MEAN_S):
                    self._start("kiss", now)

        if dozing:
            name = "sleep"
        elif self._act is not None:
            name = self._act[self._act_i][1]
        else:
            name = key
        tgt = _T.get(name, _T["green"])
        dirty = name in _ANIM or tired_changed
        if name != self._name:
            self._name = name
            self._tgt = tgt
            dirty = True
        e = tgt["ease"]
        c = self.cur
        for k in _KEYS:
            d = tgt[k] - c[k]
            if d > 0.05 or d < -0.05:
                c[k] += d * e
                dirty = True
            else:
                c[k] = float(tgt[k])
        if dirty:
            self._dirty = True
        self.lid = c["lid"]

    # ── Zeichnen ─────────────────────────────────────────────
    def draw(self, g, pens, now):
        """pens = (Brauen-Pen, Mund-Pen, Rosa-Pen, Hintergrund-Pen). Reihenfolge:
        Mund, Brauen, Herzen. Umrisse werden nur bei Bewegung neu berechnet."""
        if self._dirty:
            self._dirty = False
            self._ops = []
            self._mouth(now)
            if not self._tgt["hide"]:
                self._brows()
        for role, pts in self._ops:
            g.set_pen(pens[role])
            g.polygon(pts)
        if self._act is not None and self._act_kind == "kiss" and self._name == "k1":
            self._hearts_draw(g, pens[2], now)
        elif self._name == "pfiff":
            self._hearts_draw(g, pens[2], now, both=True)

    @property
    def heart_eyes(self):
        """Pfiff: eyes.py zeichnet Herzen statt Pupillen."""
        return self._name == "pfiff"

    def pupil_heart(self, g, pen, x, y, now):
        """Herz als Pupille, pulsiert etwa 1,5-mal pro Sekunde."""
        t = time.ticks_diff(now, self._t0) / 1000
        s = 34 + 4 * math.sin(2 * math.pi * t / 0.7)
        self._heart(g, pen, x, y - 0.175 * s, s)

    # Brauen: Polygon mit Knick und leicht abgeschraegten Enden (~Rundung)
    def _brows(self):
        c = self.cur
        drop = 3 * self._tired
        for i in (0, 1):
            xo, xi = _BROW_X[i]
            xo += _CX[i]
            xi += _CX[i]
            oy = (c["boL"] if i == 0 else c["boR"]) + drop
            iy = c["biL"] if i == 0 else c["biR"]
            xk = xo + (xi - xo) * c["kf"]
            yk = oy + (iy - oy) * c["kf"] - 1.6 * c["ba"]
            self._poly_brow(xo, oy, xk, yk, xi, iy, 3.5)

    def _poly_brow(self, x0, y0, x1, y1, x2, y2, hw):
        def nrm(ax, ay, bx, by):
            dx, dy = bx - ax, by - ay
            ln = math.sqrt(dx * dx + dy * dy) or 1.0
            return dx / ln, dy / ln
        d1 = nrm(x0, y0, x1, y1)
        d2 = nrm(x1, y1, x2, y2)
        n1 = (-d1[1], d1[0])
        n2 = (-d2[1], d2[0])
        mx, my = n1[0] + n2[0], n1[1] + n2[1]
        ml = math.sqrt(mx * mx + my * my) or 1.0
        mx, my = mx / ml, my / ml
        k = hw / (mx * n1[0] + my * n1[1])
        ch = 1.5                                         # Abschraegung der Enden
        pts = (
            # links herum: Anfang, Knick, Ende
            (x0 + hw * n1[0] - ch * n1[0], y0 + hw * n1[1] - ch * n1[1]),
            (x0 + hw * n1[0] + ch * d1[0], y0 + hw * n1[1] + ch * d1[1]),
            (x1 + k * mx, y1 + k * my),
            (x2 + hw * n2[0] - ch * d2[0], y2 + hw * n2[1] - ch * d2[1]),
            (x2 + hw * n2[0] - ch * n2[0], y2 + hw * n2[1] - ch * n2[1]),
            (x2 - hw * n2[0] + ch * n2[0], y2 - hw * n2[1] + ch * n2[1]),
            (x2 - hw * n2[0] - ch * d2[0], y2 - hw * n2[1] - ch * d2[1]),
            (x1 - k * mx, y1 - k * my),
            (x0 - hw * n1[0] + ch * d1[0], y0 - hw * n1[1] + ch * d1[1]),
            (x0 - hw * n1[0] + ch * n1[0], y0 - hw * n1[1] + ch * n1[1]),
        )
        self._ops.append((0, [(int(px + 0.5), int(py + 0.5)) for px, py in pts]))

    # Mund
    def _mouth(self, now):
        t = time.ticks_diff(now, self._t0) / 1000
        if self._tgt["kind"]:
            self._ellipse(t)
        else:
            self._lens(t)

    def _lens(self, t):
        c = self.cur
        w = c["w"] * (1 - 0.1 * self._tired if self._name == "green" else 1)
        cl, cr, qt, qb = c["cl"], c["cr"], c["qt"], c["qb"]
        A, dr, ym = c["A"], c["dr"], c["ym"]
        if self._name == "listen":                   # minimale Bewegung: "Hmmm"
            w += 2.0 * math.sin(t * 2.4)
            cr += 1.2 * math.sin(t * 3.7 + 1.0)
            qb += 1.5 * math.sin(t * 2.4 + 0.6)
        xl = 120 - w / 2
        yl, yr = ym - cl, ym - cr
        up = []
        lo = []
        n = _N
        for k in range(n + 1):
            s = k / n
            u = 1 - s
            base = u * u * yl + 2 * s * u * (ym + qt) + s * s * yr
            base2 = u * u * yl + 2 * s * u * (ym + qb) + s * s * yr
            extra = -A * math.sin(2 * math.pi * s) + dr * (2 * s - 1) ** 2
            x = xl + w * s
            up.append((x, base + extra))
            lo.append((x, base2 + extra))
        opening = (qb - qt) / 2
        ops = self._ops
        dim = self._tgt["dim"] and c["w"] > 60
        if opening < 3:                              # geschlossen: Band um die Kurve
            mid = [(x, (a + b[1]) / 2) for (x, a), b in zip(up, lo)]
            ops.append((1, [(int(x + 0.5), int(y - 2.5 + 0.5)) for x, y in mid] +
                        [(int(x + 0.5), int(y + 2.5 + 0.5)) for x, y in reversed(mid)]))
            if dim:
                self._dimples(xl, yl, xl + w, yr)
            return
        ops.append((1, [(int(x + 0.5), int(y - 2.5 + 0.5)) for x, y in up] +
                    [(int(x + 0.5), int(y + 2.5 + 0.5)) for x, y in reversed(lo)]))
        if opening > 6:                              # Innenraum dunkel
            ops.append((3, [(int(x + 0.5), int(y + 2.5 + 0.5)) for x, y in up] +
                        [(int(x + 0.5), int(y - 2.5 + 0.5)) for x, y in reversed(lo)]))
        if opening > 11:                             # weit offen: rosa Zunge
            mx, my = lo[n // 2]
            self._oval(2, 120, my - 9, w * 0.2, 6)
        if dim:
            self._dimples(xl, yl, xl + w, yr)

    def _dimples(self, xl, yl, xr, yr):
        """Gruebchen: kleiner Knick-Bogen ausserhalb jedes Mundwinkels, als
        duenne Polygone (je 3 Punkte, ~2 px)."""
        for sx, xx, yy in ((-1, xl, yl), (1, xr, yr)):
            a = (int(xx + sx * 3), int(yy - 7))
            b = (int(xx + sx * 7), int(yy - 1))
            d = (int(xx + sx * 3), int(yy + 5))
            self._ops.append((1, [a, b, d, (d[0], d[1] + 2), (b[0] + sx * 1, b[1] + 1), (a[0], a[1] + 2)]))

    def _oval(self, role, cx, cy, rx, ry):
        self._ops.append((role, [(int(cx + rx * c + 0.5), int(cy + ry * s + 0.5)) for c, s in _ELL]))

    def _ellipse(self, t):
        c = self.cur
        rx, ry, ex, ym = c["rx"], c["ry"], c["ex"], c["ym"]
        if self._name == "sleep":                    # Atmen, im Takt der Lider
            ry += 1.0 * math.sin(2 * math.pi * t / 6.0)
        elif self._name in ("k1", "pfiff"):          # dezentes Pulsieren
            p = math.sin(2 * math.pi * t / 1.4)
            rx += 1.3 * p
            ry += 1.3 * p
        self._oval(1, ex, ym, rx + 2.5, ry + 2.5)
        if not self._tgt["solid"]:
            self._oval(3, ex, ym, rx - 2.5, ry - 2.5)
            if ry >= 20:                             # Gaehnen: rosa Zunge unten
                self._oval(2, ex, ym + ry - 9, rx * 0.6, 7)

    # Herzen (Kuss): zwei, zeitversetzt, steigen schraeg auf und schrumpfen
    def _hearts_draw(self, g, pink, now, both=False):
        t = time.ticks_diff(now, self._t0)
        for off in (0, 1200):
            f = ((t + off) % 2400) / 2400
            if f > 0.85:
                continue
            f = f / 0.85
            self._heart(g, pink, 150 + 18 * f, 198 - 24 * f, 15 - 7 * f)
            if both:                                 # Pfiff: auch links, versetzt
                f2 = ((t + off + 600) % 2400) / 2400
                if f2 <= 0.85:
                    f2 = f2 / 0.85
                    self._heart(g, pink, 90 - 18 * f2, 198 - 24 * f2, 15 - 7 * f2)

    @staticmethod
    def _heart(g, pen, x, y, s):
        r = s / 4
        g.set_pen(pen)
        g.circle(int(x - r), int(y), max(1, int(r + 0.5)))
        g.circle(int(x + r), int(y), max(1, int(r + 0.5)))
        g.polygon([(int(x - 2 * r), int(y + r * 0.4)), (int(x + 2 * r), int(y + r * 0.4)),
                   (int(x), int(y + 2.4 * r))])

# EOF 2026-11-18
