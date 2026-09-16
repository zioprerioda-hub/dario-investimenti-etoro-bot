# dario-investimenti-etoro-bot

Monitor GitHub Actions che segue il portafoglio pubblico di `thomaspj` tramite eToro, invia notifiche Telegram e genera un report HTML dettagliato allegato direttamente al messaggio Telegram.

## Cosa fa

- segue `thomaspj` su eToro;
- controlla il portafoglio pubblico live ogni ~5 minuti tramite GitHub Actions;
- usa `positionId` per distinguere aperture e chiusure dalle normali variazioni di prezzo;
- invia su Telegram le variazioni rilevate;
- calcola l'importo equivalente in euro sul capitale replica configurato;
- invia il riepilogo completo circa ogni 10 minuti;
- genera e allega a Telegram un file `Report_thomaspj_YYYY-MM-DD_HH-MM.html` circa ogni 10 minuti;
- mantiene la dashboard HTML dettagliata in stile BullAware con le sezioni Overview, Trades, Seasonality, History, Correlations, Risk, Activity, Dividends, Positions, Copiers e Feed Analytics;
- alimenta il report con i dati eToro disponibili e con lo storico accumulato dal monitor;
- salva lo stato del monitor in `state.json` e lo storico necessario al report in `dashboard_state.json`.

## Report HTML Telegram

Il report non richiede GitHub Pages. Il workflow ricostruisce il motore del report e il template HTML, recupera i dati eToro e invia il file HTML direttamente tramite Telegram.

L'esecuzione manuale da **Actions → Monitor thomaspj on eToro → Run workflow** forza l'invio di un nuovo report HTML anche se non sono ancora trascorsi 10 minuti dall'ultimo invio.

Le credenziali eToro e Telegram restano nei GitHub Secrets e non vengono inserite nel file HTML.

## Dati

Il report usa i dati esposti dagli endpoint eToro disponibili, tra cui portafoglio live, anagrafica pubblica, informazioni di trading, performance e market data. Le sezioni che richiedono uno storico locale diventano più complete man mano che il monitor raccoglie nuovi snapshot. Se un dato non è disponibile tramite eToro, il report non inventa un valore.

> Il progetto monitora e riporta dati. Non esegue automaticamente ordini sul conto eToro.
