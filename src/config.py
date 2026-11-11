# config.py
# Zentrale Konfiguration. Alles, was du beim Kalibrieren oder Umbauen anfasst,
# steht hier - nicht verstreut im Code.

# ── I2C (BME688 + LTR-559) ────────────────────────────────
# Enviro+ Pack: Breakout-Garden-Bus auf GP4/GP5.
I2C_SDA = 4
I2C_SCL = 5
BME_ADDRESS = 0x77
# Angeglichen an das BME690-Projekt (2026-09-xx), um die Gaswiderstands-
# Charakteristik zwischen beiden Geraeten vergleichbarer zu machen.
# Bibliotheks-Default waere 300 C / 100 ms - bewusst abweichend gesetzt.
BME_HEATER_TEMP_C = 320
BME_HEATER_DURATION_MS = 150
# LTR-559 hat eine feste Adresse und wird vom Treiber selbst gesetzt.

# ── Mikrofon ──────────────────────────────────────────────
# Analoges MEMS-Mic. Laut Enviro+-Schaltplan liegt MIC_OUT auf ADC0 = GP26 (bestaetigt).
MIC_ADC_PIN = 26
MIC_SAMPLES = 512        # Samples pro Pegelmessung (Burst)
# sensors.py rechnet mit den echten 12-Bit-ADC-Werten (read_u16() >> 4),
# damit die RMS-Berechnung mit Ganzzahlen statt Heap-Floats auskommt.
# Vollausschlag daher 2048 statt 32768 - dBFS-Werte bleiben praktisch gleich.
MIC_FULLSCALE = 2048     # halber 12-Bit-ADC-Hub (0..4095)
MIC_DB_TRIM = 0.0        # optionaler Offset in dB, rein kosmetisch

# ── RGB-LED (oben mittig am LCD) ──────────────────────────
LED_R = 6
LED_G = 7
LED_B = 10               # per REPL-Test bestaetigt (nicht GP8 - die PDF-Text-
                          # extraktion des Schaltplans hatte hier geirrt)
LED_INVERT = True        # gemeinsame Anode -> invertiert ansteuern
# Ampelfarbe nur in der Datenansicht, im Bildschirmschoner und in der
# Aufwaermphase aus. Helligkeit als Tastverhaeltnis 0..1 (16-Bit-PWM);
# 0.002 = 0,2 %, per REPL-Test bei Tag und im Dunkeln gut erkennbar.
LED_IAQ_DUTY = 0.002
LED_YELLOW_GREEN = 0.7   # Gruenanteil fuer Gelb (Rot = 1.0)

# ── Buttons ───────────────────────────────────────────────
BTN_A = 12   # Einfachklick: Daten <-> Augen, Doppelklick: Display drehen
BTN_B = 13   # WLAN/Webserver an/aus; setzt den WLAN-Zeitplan bis zum
             # naechsten Schaltpunkt aus
BTN_X = 14   # naechste Seite
BTN_Y = 15   # vorige Seite

# ── Display ───────────────────────────────────────────────
BRIGHTNESS = 0.8         # Backlight Datenansicht 0.0..1.0 (gamma-korrigiert)

# Bildschirmschoner "Augen" (eyes.py). Helligkeit stufenlos nach Umgebungs-
# licht: Punkte (Lux, Helligkeit), dazwischen linear, ausserhalb konstant.
# Lux-Messung 2026-11-11 am Schreibtisch (Display aus): tagsueber 8,5-9,7,
# am Fenster 40-218, nachts ~0-4. Am Geraet abgestimmt (Variante 1):
# mindestens 0.6 (24 %). Keine eigene Nachtstufe: am Schreibtisch misst der
# Sensor abends mit Lampe ebenfalls ~0 Lux, eine Nachtstufe griff dann schon
# am Abend. Eigenlicht der Augen kommt am Sensor praktisch nicht an (0 Lux
# bei leuchtenden Augen gemessen).
EYES_BRIGHTNESS_CURVE = ((9, 0.60), (60, 0.70), (250, 0.90))
EYES_SMOOTH = 0.35            # Anteil pro Messung (alle 3 s), ~90 % nach 15 s
# Schlafmodus: im WLAN-Aus-Fenster (WIFI_OFF_FROM bis WIFI_OFF_UNTIL) schliessen
# die Augen bis auf einen schmalen Streifen; Backlight dann fest auf diesem
# Wert statt nach Lichtkurve. Die weissen Flaechen sind dann fast weg - die
# Kontur bleibt auch bei niedriger Stufe gut sichtbar.
EYES_SLEEP_BRIGHTNESS = 0.4   # ~7,7 % Tastverhaeltnis
EYES_FRAME_MS = 80            # 12,5 Bilder/s; ein Vollbild-Update dauert ~45 ms

# Doppelklick auf Taste A dreht die Anzeige um 90 Grad weiter. Ein
# Einfachklick wird erst nach DOUBLE_CLICK_MS ausgefuehrt - erst dann steht
# fest, dass kein zweiter Klick kommt.
DOUBLE_CLICK_MS = 350
# Drehfolge. Dreht 90 auf deinem Board gegen den Uhrzeigersinn, hier
# (0, 270, 180, 90) eintragen.
ROTATIONS = (0, 90, 180, 270)
ROTATION_FILE = "rotation.txt"   # letzte Lage, uebersteht einen Neustart

# ── Kalibrierung Klima ────────────────────────────────────
# TEMP_OFFSET wird vom Rohwert ABGEZOGEN (Sensor liest durch Eigenwaerme zu hoch).
# Ein einziger Wert (Kalibrierpaket 2026-09-24): Die Hauptwaerme kommt vom
# gesockelten Pico (CPU + WLAN, Powersave aus) und bleibt konstant. Das
# Backlight laeuft nur kurz nach Neustart bzw. beim Nachsehen; die fruehere
# ON/OFF-Umschaltung sprang sofort, waehrend die Waerme sich ueber Minuten
# aendert, und erzeugte dadurch groessere Fehler als ein fester Wert.
# Abgleich 23./24.09. gegen SwitchBot (Fensterbank) und Wandsensor:
# +0.8/+1.0/+1.3 bzw. +1.2/+1.2/+0.8 C ueber altem OFF-Wert 4.35.
# Bei laengerem Backlight-Betrieb (>~20 min) liest das Geraet zu hoch.
# ACHTUNG (2026-11-10): Mit dem Augen-Bildschirmschoner laeuft das Backlight
# dauerhaft (schwach) und die CPU zeichnet laufend. Wert nach einigen Tagen
# gegen die Referenz neu abgleichen.
TEMP_OFFSET = 5.4
# Feuchte wird physikalisch ueber Magnus auf die korrigierte Temperatur zurueckgerechnet
# (siehe sensors.py). HUMIDITY_TRIM ist nur die letzte empirische Feinjustage
# gegen dein Referenzgeraet (SwitchBot/Enviro+), additiv in %-Punkten.
HUMIDITY_TRIM = 0.0
# Hoehe ueber NN in Metern, fuer die Umrechnung auf Meeresspiegeldruck.
ALTITUDE = 8
# DWD-Vergleich (2026-09-xx): Enviro+ zeigte 1014 hPa bei 1013 hPa Referenz -> zu hoch.
PRESSURE_OFFSET_HPA = -1.0

# ── Idealbereiche fuer Ampel-Faerbung (nur Dashboard) ─────
# Innerhalb -> gruen, ausserhalb -> neutral/gelb.
TEMP_IDEAL = (20.0, 24.0)
HUMIDITY_IDEAL = (40.0, 60.0)
# Druck hat KEINEN Idealbereich - bewusst keine Ampel, Bewertung ueber Wettertrend.

# ── Relative IAQ-Baseline (Gaswiderstand) ─────────────────
# Paket 2: gemeinsames Modul iaq.py (identisch beim BME690).
IAQ_HALFLIFE_H = 6.0          # Huellkurven vergessen alte Extremwerte mit dieser Halbwertszeit
IAQ_MIN_RATIO = 2.0           # Mindestspanne hi/lo; gleichbleibende Luft zeigt "gut"
IAQ_WARMUP_S = 1200           # 20 min nach Start: Heizer kalt, Werte unbrauchbar -> "Aufwärmphase"
IAQ_BASELINE_FILE = "iaq_baseline.txt"
# Score-Schwellen (0..1) fuer Label + LED-Farbe.
IAQ_GOOD = 0.66
IAQ_OK = 0.33

# ── Verlauf (Sparklines) ──────────────────────────────────
HISTORY_LEN = 180            # Punkte; 180 x 60 s = 3 h
HISTORY_INTERVAL_MS = 60000  # ein Verlaufspunkt pro Minute

# ── Takt-Intervalle (nicht blockierend) ───────────────────
SENSOR_INTERVAL_MS = 3000    # BME/LTR lesen (Paket 2: 3 s statt 1 s -> weniger Heizerwaerme)
LOOP_SLEEP_MS = 10           # Bremse pro Schleifendurchlauf - fehlte bisher
AUTO_OFF_IDLE_MS = 2 * 60 * 1000   # Augen-Bildschirmschoner nach 2 Min. ohne Tastendruck
MIC_INTERVAL_MS = 500        # Pegel messen (laufend - Display UND Web zeigen ihn)
DISPLAY_INTERVAL_MS = 500    # Bildschirm neu zeichnen
INTERNAL_TEMP_INTERVAL_MS = 10000  # interne Pico-Temp, langsam wechselnd
SYSTEM_INTERVAL_MS = 2000    # RAM/Flash-Abfrage (statvfs kostet etwas)
# Groesster zusammenhaengender freier Heap-Block. Die Sonde loest bei jedem
# Fehlversuch intern eine Garbage Collection aus - deshalb seltener als RAM.
HEAP_PROBE_INTERVAL_MS = 10000
IAQ_SAVE_INTERVAL_MS = 300000  # Baseline alle 5 min auf Flash sichern
TREND_WINDOW_MS = 600000     # 10 min Fenster fuer "+x / 10 min"-Deltas
TREND_SAMPLE_INTERVAL_MS = 30000  # Trend-Snapshot alle 30 s (20 Punkte / 10 min)

# ── Webserver ─────────────────────────────────────────────
WEB_PORT = 80

# WLAN-Verhalten (gleiche Werte wie beim BME690)
WIFI_CHECK_MS = 1000       # Linkpruefung hoechstens so oft
WIFI_RETRY_MS = 15000      # ohne Verbindung: neuer Versuch nach dieser Zeit
WIFI_RESET_AFTER = 3       # nach so vielen Fehlversuchen Schnittstelle neu starten
WIFI_COUNTRY_DEFAULT = "DE"  # falls secrets.WIFI_COUNTRY fehlt
# WLAN beim Start automatisch einschalten (wie beim BME690).
# Auskommentiert = WLAN startet aus, Taste B schaltet ein.
WIFI_AUTOSTART = True
# WLAN-Nachtabschaltung (wifi_schedule.py, identisch beim BME690). Die
# FRITZ!Box schaltet ihr WLAN 00:10-05:55 ab; der Pico trennt sich vorher
# und verbindet sich erst danach wieder. Ortszeit, Fenster ueber Mitternacht
# ist erlaubt.
WIFI_OFF_FROM = (0, 0)
WIFI_OFF_UNTIL = (6, 0)
# Der Reihe nach probiert. Die FRITZ!Box beantwortet keine NTP-Anfragen
# (ETIMEDOUT, Zeitserver im Heimnetz nicht aktiv) - deshalb nur der Pool.
NTP_HOSTS = ("pool.ntp.org",)
NTP_RESYNC_MS = 6 * 3600 * 1000             # Zeitabgleich alle 6 h
NTP_RETRY_MS = 60 * 1000                    # nach Fehlschlag in 1 min erneut
WEB_REFRESH_S = 5            # Auto-Reload der Messwerte im Browser
WEB_CHART_REFRESH_S = 60     # Auto-Reload der Diagramme

# ── Watchdog ──────────────────────────────────────────────
# Rebootet den Pico automatisch, falls sich die Hauptschleife aufhaengt.
# 0 = deaktiviert. Max. 8388 ms auf dem RP2040.
# WAEHREND DER ENTWICKLUNG MIT THONNY AUF 0 LASSEN: einmal erzeugt, laesst
# sich der WDT nicht mehr abschalten - "Stop" in Thonny fuettert ihn nicht
# mehr, nach TIMEOUT resettet er den Chip und Thonny meldet Verbindungsverlust.
# Erst scharf schalten (z.B. 8000), wenn das Geraet eigenstaendig laeuft.
WDT_TIMEOUT_MS = 0

# EOF 2026-11-10
