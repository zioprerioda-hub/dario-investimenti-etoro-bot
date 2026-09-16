# Avvio del report con un timer esterno

## Stato verificato il 16 settembre 2026

Alle 18:42 UTC il workflow `monitor.yml` era attivo, ma lo storico disponibile conteneva zero esecuzioni con evento `schedule`. Il ripristino ha disattivato e riattivato lo stesso workflow, verificando lo stato finale `active`. Il controllo delle 18:47:52 UTC, dopo il successivo orario previsto delle 18:47 UTC, mostrava ancora zero esecuzioni programmate. La ripartenza automatica quindi non è confermata.

Il report e l'invio Telegram funzionano negli avvii manuali e su modifica del workflow. La configurazione seguente è pronta per un timer esterno, ma **non è attivata**: richiede un account cron-job.org e un token GitHub dedicato.

## Configurazione cron-job.org

1. Crea un account su https://console.cron-job.org/signup.
2. In GitHub crea un **fine-grained personal access token** da https://github.com/settings/personal-access-tokens/new.
   - Proprietario: `zioprerioda-hub`.
   - Accesso soltanto a `dario-investimenti-etoro-bot`.
   - Permesso del repository: **Actions — Read and write**.
   - Imposta una scadenza e annotala: alla scadenza il timer richiederà un token nuovo.
3. Crea un cronjob con questi campi:

| Campo | Valore |
| --- | --- |
| Titolo | Report eToro ogni 10 minuti |
| URL | `https://api.github.com/repos/zioprerioda-hub/dario-investimenti-etoro-bot/actions/workflows/monitor.yml/dispatches` |
| Metodo HTTP | `POST` |
| Frequenza | Ogni 10 minuti, tutti i giorni |
| Corpo della richiesta | `{"ref":"main"}` |
| Header `Authorization` | `Bearer TOKEN_GITHUB` |
| Header `Accept` | `application/vnd.github+json` |
| Header `Content-Type` | `application/json` |
| Header `X-GitHub-Api-Version` | `2022-11-28` |

Inserisci il token direttamente nel campo Authorization di cron-job.org. Non salvarlo nel repository né inviarlo in chat. Le credenziali eToro e Telegram rimangono nei Secrets di GitHub.

## Attivazione e verifica

- Esegui il test del cronjob e verifica una risposta HTTP 2xx.
- Controlla in GitHub Actions che compaia una nuova esecuzione `workflow_dispatch`, che termini con successo e che Telegram riceva riepilogo e HTML.
- Dopo il test, usa soltanto il timer esterno: rimuovi il blocco `schedule` da `monitor.yml` mantenendo `workflow_dispatch`. Non disabilitare l'intero workflow. Questo evita doppi messaggi se il cron GitHub riparte.
- Attiva il cronjob e controlla almeno due invii consecutivi distanziati di circa 10 minuti.
- Una risposta HTTP 2xx conferma la richiesta di avvio; per confermare l'invio serve anche il risultato del workflow.
- Il timer esterno evita di dipendere dal cron GitHub; il tempo di attesa del runner e la generazione del report possono comunque variare.

cron-job.org offre il timer gratuito. Le esecuzioni continuano a consumare la quota GitHub Actions del repository privato: sono 144 avvii al giorno, quindi non implica esecuzioni GitHub illimitate gratuite.

Fonti:
- https://cron-job.org/en/
- https://cron-job.org/en/faq/
- https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
