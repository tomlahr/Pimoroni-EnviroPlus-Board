# sensors.py
# Sensorschicht. Jeder Sensor kapselt sein Lesen und liefert saubere Werte
# als dict oder Zahl zurueck - kein Tupel-Entpacken mehr im Hauptcode.

import math
import machine
from machine import ADC
from pimoroni_i2c import PimoroniI2C
from breakout_bme68x import (
    BreakoutBME68X, STATUS_HEATER_STABLE,
    FILTER_COEFF_3, STANDBY_TIME_1000_MS,
    OVERSAMPLING_1X, OVERSAMPLING_2X, OVERSAMPLING_16X,
)
try:
    from breakout_bme68x import STATUS_GAS_VALID
    _HAS_GAS_VALID = True
except ImportError:
    STATUS_GAS_VALID = 0
    _HAS_GAS_VALID = False
from breakout_ltr559 import BreakoutLTR559

import config


def make_i2c():
    """Einen I2C-Bus fuer BME688 und LTR-559 erzeugen."""
    return PimoroniI2C(sda=config.I2C_SDA, scl=config.I2C_SCL)


def saturation_vapor_pressure(t):
    """Saettigungsdampfdruck nach Magnus in hPa."""
    return 6.112 * math.exp((17.62 * t) / (243.12 + t))


def dewpoint(temp_c, humidity_pct):
    """Taupunkt in C - invertierte Magnus-Formel."""
    rh = max(0.1, min(100.0, humidity_pct))
    e = (rh / 100.0) * saturation_vapor_pressure(temp_c)
    ln_ratio = math.log(e / 6.112)
    return (243.12 * ln_ratio) / (17.62 - ln_ratio)


def vpd_kpa(temp_c, humidity_pct):
    """Vapor Pressure Deficit in kPa - gebraeuchliche Einheit im Pflanzenbau."""
    es = saturation_vapor_pressure(temp_c)
    e = (humidity_pct / 100.0) * es
    return (es - e) / 10.0  # hPa -> kPa


# ══════════════════════════════════════════════════════════
#  BME688: Temperatur, Druck, Feuchte, Gas
# ══════════════════════════════════════════════════════════
class Weather:
    def __init__(self, i2c):
        self.bme = BreakoutBME68X(i2c, address=config.BME_ADDRESS)
        self.bme.configure(
            FILTER_COEFF_3, STANDBY_TIME_1000_MS,
            OVERSAMPLING_1X, OVERSAMPLING_2X, OVERSAMPLING_16X,
        )
        self.temp_offset = config.TEMP_OFFSET
        self.humidity_trim = config.HUMIDITY_TRIM
        self.altitude = config.ALTITUDE

    def warmup(self, reads=3, delay_ms=500):
        """Erste Messungen verwerfen - der Heizer braucht ein paar Zyklen."""
        import time
        for _ in range(reads):
            try:
                self.bme.read(
                    heater_temp=config.BME_HEATER_TEMP_C,
                    heater_duration=config.BME_HEATER_DURATION_MS,
                )
            except Exception:
                pass
            time.sleep_ms(delay_ms)

    def _correct_humidity(self, t_raw, rh_raw, t_corr):
        # Absolute Feuchte bleibt gleich; nur die relative Feuchte wird auf die
        # korrigierte (kuehlere) Temperatur zurueckgerechnet. Kein additiver Pfusch.
        rh = rh_raw * saturation_vapor_pressure(t_raw) / saturation_vapor_pressure(t_corr)
        rh += self.humidity_trim
        if rh > 100.0:
            rh = 100.0
        if rh < 0.0:
            rh = 0.0
        return rh

    def _sea_level(self, p_hpa, t):
        a = self.altitude
        return p_hpa + ((p_hpa * 9.80665 * a) / (287 * (273 + t + (a / 400))))

    def read(self):
        t, p, h, g, status, _, _ = self.bme.read(
            heater_temp=config.BME_HEATER_TEMP_C,
            heater_duration=config.BME_HEATER_DURATION_MS,
        )
        heater_stable = bool(status & STATUS_HEATER_STABLE)
        gas_valid = bool(status & STATUS_GAS_VALID) if _HAS_GAS_VALID else None

        t_corr = t - self.temp_offset
        return {
            "temp": t_corr,
            "temp_raw": t,
            "pressure": self._sea_level(p / 100.0, t_corr) + config.PRESSURE_OFFSET_HPA,
            "humidity": self._correct_humidity(t, h, t_corr),
            "humidity_raw": h,
            "gas_kohm": g / 1000.0,
            "heater_stable": heater_stable,
            "gas_valid": gas_valid,
        }


# ══════════════════════════════════════════════════════════
#  LTR-559: Umgebungslicht
# ══════════════════════════════════════════════════════════
class Light:
    def __init__(self, i2c):
        self.ltr = BreakoutLTR559(i2c)

    def read(self):
        r = self.ltr.get_reading()
        if r is None:
            return None
        return r[BreakoutLTR559.LUX]


# ══════════════════════════════════════════════════════════
#  Mikrofon: relativer Pegel in dBFS (0 dB = ADC-Vollausschlag)
#  Kein kalibrierter Schalldruck - bewusst als "rel." beschriftet.
# ══════════════════════════════════════════════════════════
class Microphone:
    def __init__(self):
        from array import array
        self.adc = ADC(config.MIC_ADC_PIN)
        self.n = config.MIC_SAMPLES
        self.buf = array("H", (0 for _ in range(self.n)))
        self.fullscale = config.MIC_FULLSCALE
        self.trim = config.MIC_DB_TRIM

    def read_dbfs(self):
        # Reine Ganzzahl-Rechnung: Auf dem RP2040 legt MicroPython jede Float
        # als eigenes Heap-Objekt an. Die alte Float-Schleife erzeugte pro
        # Aufruf ~1.500 Objekte (~24 kB Muell, 2x pro Sekunde) - ein
        # Hauptverdaechtiger fuer die Heap-Fragmentierung.
        # read_u16() liefert den 12-Bit-Rohwert, auf 16 Bit hochskaliert;
        # >> 4 holt den Rohwert verlustfrei zurueck.
        buf = self.buf
        adc = self.adc
        n = self.n
        for i in range(n):
            buf[i] = adc.read_u16() >> 4

        mean = (sum(buf) + n // 2) // n   # gerundet statt abgeschnitten
        sq = 0
        for v in buf:
            d = v - mean
            sq += d * d
        rms = math.sqrt(sq / n)
        # Untergrenze = alte Grenze (1 von 32768) im neuen Massstab.
        if rms < 0.0625:
            rms = 0.0625
        return 20.0 * math.log10(rms / self.fullscale) + self.trim

    def describe(self, dbfs):
        if dbfs < -50:
            return "leise"
        elif dbfs < -25:
            return "normal"
        else:
            return "laut"


# ══════════════════════════════════════════════════════════
#  Interne RP2040-Temperatur (ADC-Kanal 4)
#  Grober Indikator - liest durch Eigenerwaermung zu hoch.
#  Teilt sich den ADC mit dem Mic: nur lesen, wenn kein Mic-Sampling laeuft.
# ══════════════════════════════════════════════════════════
class InternalTemp:
    def __init__(self):
        self.adc = ADC(4)

    def read(self):
        volt = self.adc.read_u16() * 3.3 / 65535.0
        return 27.0 - (volt - 0.706) / 0.001721


# ══════════════════════════════════════════════════════════
#  Relative IAQ-Baseline
#  Gleitendes Min/Max des Gaswiderstands mit langsamem Zerfall.
#  Update nur bei stabilem Heizer UND gueltigem Gaswert.
#  Baseline ueberlebt Reboot (Flash).
# ══════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════
#  Selbsttest-Naeherung
#  Boschs eigener Selbsttest prueft den internen Heizstrom-Regelwert
#  (idac) - der ist ueber diese Bibliothek nicht zugaenglich (bestaetigt:
#  bme.read() liefert 7 Werte, keiner davon idac). Diese Klasse prueft
#  stattdessen ueber mehrere Zyklen: Heizer stabil, Gaswert vom Sensor
#  als gueltig markiert, und der kOhm-Wert in einer plausiblen Spanne
#  (faengt einen offenen/kurzgeschlossenen Heizwiderstand ab, auch ohne
#  Zugriff auf idac).
# ══════════════════════════════════════════════════════════
class SelfTest:
    def __init__(self, window=5, gas_min_kohm=0.5, gas_max_kohm=5000.0):
        self.window = window
        self.gas_min = gas_min_kohm
        self.gas_max = gas_max_kohm
        self._results = []

    def update(self, heater_stable, gas_valid, gas_kohm):
        plausible = self.gas_min <= gas_kohm <= self.gas_max
        ok = bool(heater_stable) and plausible and (gas_valid is not False)
        self._results.append(ok)
        if len(self._results) > self.window:
            self._results.pop(0)

    @property
    def ready(self):
        return len(self._results) >= self.window

    def status(self):
        """(label, ok) - ok ist True/False/None (None = noch nicht genug Zyklen)."""
        if not self.ready:
            return "prüft...", None
        if all(self._results):
            return "OK", True
        return "Fehler", False


def iaq_classify(score):
    """(label, color_key) aus dem Score von iaq.IAQ.
    color_key: 'green' | 'yellow' | 'red' | 'grey'."""
    if score is None:
        return ("Aufwärmphase", "grey")
    if score >= config.IAQ_GOOD:
        return ("gute Luftqualität", "green")
    if score >= config.IAQ_OK:
        return ("mäßige Qualität", "yellow")
    return ("schlechte Luft", "red")

# EOF 2026-09-26
