# Diagnosi del timer GitHub Actions

## Esito

Il problema rimane aperto. Al 16 settembre 2026, ore **19:08:36 UTC / 21:08:36 Europe/Rome**, la cronologia disponibile del repository mostra **zero esecuzioni con evento schedule**. Il nuovo workflow è configurato soltanto per il timer nativo GitHub e per la richiesta manuale. Nessun servizio di pianificazione esterno è attivato.

## Dati verificati

| Campo | Valore |
| --- | --- |
| Repository | zioprerioda-hub/dario-investimenti-etoro-bot |
| Visibilità | Privato |
| Default branch | main |
| Archivio / fork | false / false |
| Workflow attuale | .github/workflows/report-10-minutes.yml |
| Workflow ID attuale | 359919709 |
| Stato letto tramite API alle 18:55:24 UTC | active |
| Creazione della nuova registrazione | 2026-09-16T18:54:11Z |
| Cron UTC | 6,16,26,36,46,56 * * * * |
| Commit di registrazione | a163fcfe8d97f9eca93131e3a0693bcb0567cb46 |
| Autore / committer | zioprerioda-hub / zioprerioda-hub |

Lo YAML è stato analizzato con un parser: campi validi, intervalli di dieci minuti anche al passaggio dell'ora, nessun BOM, tabulazione o carattere non ASCII. Riepilogo e HTML sono abilitati a ogni esecuzione. Le credenziali non sono riportate in questo documento.

## Prove effettuate

1. Controllo del workflow precedente: ID 359586956, stato active, cron presente in main; avvii manuali riusciti.
2. Modifica del cron fuori dall'inizio dell'ora e commit sul ramo predefinito.
3. Disattivazione e riattivazione via API alle 18:42 UTC. Stato finale active; nessun avvio schedule osservato.
4. Sostituzione atomica del vecchio file con report-10-minutes.yml, ottenendo una nuova registrazione e un nuovo ID.
5. Diagnostica in sola lettura eseguita correttamente; verifica via API di ID, stato, ramo, cron e storico.
6. Controllo periodico degli eventi schedule senza altri avvii manuali del report.

| Scadenza prevista UTC | Ora italiana | Esito al controllo finale |
| --- | --- | --- |
| 2026-09-16 18:56 | 20:56 | Nessuna esecuzione schedule nella cronologia |
| 2026-09-16 19:06 | 21:06 | Nessuna esecuzione schedule nella cronologia |

L'assenza di run non permette di identificare dal repository la causa interna esatta. La configurazione attiva e le esecuzioni riuscite su altri eventi indicano che il punto da approfondire è la generazione degli eventi programmati.

## Evidenze GitHub

- [Ultimo report di prova completato](https://github.com/zioprerioda-hub/dario-investimenti-etoro-bot/actions/runs/35134552845)
- [Disattivazione e riattivazione del workflow precedente](https://github.com/zioprerioda-hub/dario-investimenti-etoro-bot/actions/runs/35136004191)
- [Registrazione del nuovo workflow](https://github.com/zioprerioda-hub/dario-investimenti-etoro-bot/commit/a163fcfe8d97f9eca93131e3a0693bcb0567cb46)
- [Diagnostica del nuovo workflow](https://github.com/zioprerioda-hub/dario-investimenti-etoro-bot/actions/runs/35137401697)
- [Workflow attuale](https://github.com/zioprerioda-hub/dario-investimenti-etoro-bot/actions/workflows/report-10-minutes.yml)

## Riferimenti consultati

- [GitHub: troubleshooting workflows](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows#troubleshooting-workflow-triggers)
- [GitHub: schedule e actor](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [Discussione 185355: risposta sulla risincronizzazione e segnalazioni successive](https://github.com/orgs/community/discussions/185355)
- [Discussione 206028: isolamento del trigger e verifica su più scadenze](https://github.com/orgs/community/discussions/206028)

La documentazione ufficiale descrive possibili ritardi o omissioni degli eventi. Le discussioni riportano casi analoghi: non costituiscono una conferma della causa di questo repository.

## Bozza per GitHub Support — non inviata

Scheduled events are not creating workflow runs for the private repository
zioprerioda-hub/dario-investimenti-etoro-bot.

The current workflow is .github/workflows/report-10-minutes.yml, workflow ID
359919709, on the default branch main. Its state was verified as active through
the REST API. Cron: 6,16,26,36,46,56 * * * * (UTC).

Manual and push-triggered jobs have completed successfully, including report
generation and Telegram delivery. The original workflow was disabled and
re-enabled through the API. It was then replaced with a newly registered
workflow at commit a163fcfe8d97f9eca93131e3a0693bcb0567cb46.

The new workflow was registered at 2026-09-16T18:54:11Z. Expected schedule
occurrences at 18:56 and 19:06 UTC produced no visible run by 19:08:36 UTC.
GET /repos/zioprerioda-hub/dario-investimenti-etoro-bot/actions/runs?event=schedule
returned total_count=0 throughout the observation period.

Please investigate schedule registration and scheduled-event delivery for this
repository and confirm whether a backend resynchronization or an account-level
restriction is involved. The linked diagnostic runs contain the observed
metadata. We need a solution using native GitHub Actions.
