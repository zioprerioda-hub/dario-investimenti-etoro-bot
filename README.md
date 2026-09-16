# dario-investimenti-etoro-bot

Monitor GitHub Actions che legge il portafoglio pubblico live di `thomaspj` direttamente dalla Public API ufficiale di eToro e invia messaggi Telegram quando rileva nuove posizioni o posizioni chiuse.

## Cosa fa

- segue `thomaspj` su eToro;
- controlla il portafoglio pubblico live;
- usa `positionId` per distinguere vere aperture/chiusure dalle normali variazioni di prezzo;
- invia su Telegram nuove aperture e chiusure;
- calcola l'importo equivalente in euro sul capitale configurato;
- invia il portafoglio completo circa ogni 10 minuti;
- salva lo stato in `state.json` tra una esecuzione GitHub Actions e la successiva.

> Questo progetto non esegue ordini. Gli importi sono una replica proporzionale del portafoglio pubblico di `thomaspj`.
