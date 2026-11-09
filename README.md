# Boersendaten

Tägliche Marktdaten für Jans Börsen-Experiment (Probedepot gegen den Vanguard FTSE All-World).

## So funktioniert es

- Eine GitHub Action läuft Montag bis Freitag um 21:15 UTC (22:15 Uhr Winterzeit) und lässt sich unter **Actions → Marktdaten abrufen → Run workflow** auch von Hand starten.
- Das Skript `scripts/fetch_data.py` holt Tageskurse von Alpha Vantage und schreibt:
  - `data/prices/<SYMBOL>.csv`: Kursverlauf je Wertpapier. Die Historie wächst mit jedem Lauf.
  - `data/latest.json`: Momentaufnahme mit Schlusskurs, Veränderungen (1 Tag bis 12 Monate), 50- und 200-Tage-Linie, Schwankung und Fehlern.
- Welche Wertpapiere abgefragt werden, steht in `config/watchlist.json`.

## Einrichtung

Der API-Schlüssel liegt als Repository-Secret `ALPHAVANTAGE_API_KEY` (Settings → Secrets and variables → Actions). Er steht nie im Code.

## Grenzen

- Gratis-Schlüssel: höchstens 25 Abfragen pro Tag und 5 pro Minute. Ein Symbol braucht 1 Abfrage, mit 200-Tage-Linie 2.
- Kurse sind Schlusskurse, keine Echtzeitdaten. Für die Probedepot-Buchungen gilt immer der Kurs aus der Broker-App.
- Ältere Kurse als ca. 100 Handelstage liefert der Gratis-Zugang nicht. Längere Zeiträume entstehen erst durch die gesammelte Historie.
