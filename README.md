# dario-investimenti-etoro-bot

Monitor GitHub Actions che legge il portafoglio pubblico live di `thomaspj` direttamente dalla Public API ufficiale di eToro, invia notifiche Telegram e genera una dashboard HTML aggiornata.

## Cosa fa

- segue `thomaspj` su eToro;
- controlla il portafoglio pubblico live ogni ~5 minuti tramite GitHub Actions;
- usa `positionId` per distinguere vere aperture/chiusure dalle normali variazioni di prezzo;
- invia su Telegram nuove aperture e chiusure;
- calcola l'importo equivalente in euro sul capitale configurato;
- invia il portafoglio completo circa ogni 10 minuti;
- aggiunge ai messaggi Telegram il link al report HTML;
- aggiorna `docs/report.json` con prezzi, allocazioni, leva, P/L e posizioni correnti;
- salva lo stato in `state.json` tra una esecuzione GitHub Actions e la successiva.

## Report HTML

La dashboard è in `docs/index.html` e legge `docs/report.json`.

URL previsto con GitHub Pages:

`https://zioprerioda-hub.github.io/dario-investimenti-etoro-bot/`

Per pubblicarlo: **Settings → Pages → Build and deployment → Deploy from a branch → `main` → `/docs` → Save**.

La pagina controlla `report.json` ogni 30 secondi; i dati eToro sottostanti vengono aggiornati dal workflow ogni ~5 minuti. Le credenziali eToro restano nei GitHub Secrets e non vengono mai inserite nell'HTML pubblico.

> Questo progetto non esegue ordini. Gli importi sono una replica proporzionale del portafoglio pubblico di `thomaspj`.
