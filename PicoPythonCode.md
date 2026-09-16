# PicoEnviro+ - Installationshinweise

## Dateien -> Pico
Alle neun `.py`-Dateien direkt ins Wurzelverzeichnis des Pico kopieren
(z.B. per Thonny), keine Unterordner:

    secrets.py
    config.py
    sensors.py
    system.py
    wifi.py
    history.py
    web.py
    display.py
    main.py

## Vor dem ersten Start
1. `secrets.py` oeffnen und WLAN_SSID / WIFI_PASSWORD eintragen.
2. `config.py` gegen dein Referenzgeraet kalibrieren:
   - TEMP_OFFSET (Eigenerwaermung durch Gehaeuse/Display)
   - HUMIDITY_TRIM (Feinjustage nach der physikalischen Korrektur)
   - LED_B: laut Schaltplan GP8 - falls dein Board nachweislich GP10 nutzt,
     hier zuruecktauschen.
   - MIC_ADC_PIN: Arbeitsannahme GP26, noch nicht hardwareseitig verifiziert.

## Voraussetzung: Firmware
Der generische "batteries included" MicroPython-Build von
https://github.com/pimoroni/pimoroni-pico/releases (Board-Variante
`enviro.uf2`) muss bereits geflasht sein. Der bringt `picographics`,
`pimoroni`, `pimoroni_i2c`, `breakout_bme68x` und `breakout_ltr559` schon mit -
diese Bibliotheken sind NICHT Teil dieses Pakets.

## Reihenfolge beim ersten Testlauf
main.py importiert die anderen sechs Module; ein fehlender Import faellt
sofort beim Boot auf (REPL-Fehlermeldung in Thonny). Nach dem Kopieren
einmal per Ctrl+D (Soft-Reset) oder Power-Cycle neu starten.

## Nach dem Start
Taste B schaltet WLAN an/aus. Erst NACH erfolgreicher Verbindung (IP vergeben)
startet der Webserver automatisch - im Browser die IP von der WLAN-Seite
aufrufen (Taste X/Y zum Blaettern). Das Dashboard aktualisiert Messwerte alle
paar Sekunden, Diagramme jede Minute - siehe WEB_REFRESH_S / WEB_CHART_REFRESH_S
in config.py.

## Offene Punkte
- MIC_ADC_PIN (GP26) empirisch verifiziert - dB-Werte reagieren auf Geraeusche.
- WDT-Timeout (8000 ms) im Auge behalten, falls die Firmware eine andere
  Obergrenze durchsetzt.
- web.py ist nicht auf echter Hardware getestet (kann in dieser Umgebung
  nicht laufen) - erster Praxistest steht noch aus. Bei Problemen: Browser-
  Konsole (F12) auf Netzwerkfehler pruefen, sowie ob /data und /history
  einzeln im Browser aufgerufen brauchbares JSON liefern.
- MQTT/Home-Assistant-Anbindung ist bewusst noch nicht Teil dieses Pakets
  (Option b aus der urspruenglichen Planung) - kann bei Bedarf ergaenzt werden.
