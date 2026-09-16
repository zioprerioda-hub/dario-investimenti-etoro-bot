# Azure Functions setup

Il repository è pronto per essere eseguito come **Azure Function Timer Trigger** ogni 10 minuti.

## Architettura

- `function_app.py` = timer Azure Functions
- `scheduled_runner.py` = pipeline esistente eToro -> Telegram -> HTML
- `azure_state.py` = persistenza di `state.json`, `html_report_state.json` e `dashboard_state.json` su Azure Blob Storage
- `host.json` = configurazione runtime Azure Functions

## 1. Creare la Function App

Nel portale Azure:

1. **Create a resource** -> **Function App**
2. Hosting: **Flex Consumption**
3. Runtime stack: **Python**
4. Runtime version: **3.11** o altra versione Python supportata dalla Function App
5. Region: una regione vicina/supportata
6. Creare/associare uno Storage Account
7. Creare la risorsa

## 2. App settings

In Function App -> Settings / Environment variables aggiungere:

- `TIMER_SCHEDULE` = `0 */10 * * * *`
- `ETORO_API_KEY` = chiave pubblica eToro
- `ETORO_USER_KEY` = chiave privata/user key eToro
- `TELEGRAM_BOT_TOKEN` = token Telegram
- `TELEGRAM_CHAT_ID` = chat id Telegram
- `ETORO_USERNAME` = `thomaspj`
- `PORTFOLIO_EUR` = `5000`
- `MIN_ALERT_EUR` = `5`
- `PORTFOLIO_SUMMARY_MINUTES` = `10`
- `HTML_REPORT_MINUTES` = `10`
- `RISK_FREE_ANNUAL` = `0`
- `AZURE_STATE_CONTAINER` = `bot-state`
- `REPORT_URL` = vuoto
- `REPORT_DIR` = `docs`
- `SEND_INITIAL_PORTFOLIO` = `true`
- `TREEMAP_HISTORY_HOURS` = `12`
- `TREEMAP_HISTORY_LIMIT` = `20`

`AzureWebJobsStorage` viene normalmente creato/configurato automaticamente dalla Function App. Il codice usa lo stesso account per salvare lo stato del bot.

## 3. Deploy dal repository GitHub

In Function App -> **Deployment Center**:

1. Source: **GitHub**
2. Autorizzare l'account GitHub
3. Repository: `zioprerioda-hub/dario-investimenti-etoro-bot`
4. Branch: `main`
5. Provider: GitHub Actions / impostazione raccomandata dal portale
6. Salvare e attendere il deploy

Il workflow creato da Azure serve solo per **deployare il codice**. Il timer ogni 10 minuti viene eseguito da Azure Functions, non dal cron di GitHub.

## 4. Verifica

Dopo il deploy:

1. Function App -> Functions
2. Deve comparire `thomaspj_report_timer`
3. Function App -> Log stream / Application Insights
4. Attendere il successivo minuto `00, 10, 20, 30, 40, 50`
5. Nei log deve apparire `Starting scheduled_runner.py from Azure Functions`
6. Telegram deve ricevere riepilogo e file HTML

Il timer usa `use_monitor=True`, quindi Azure registra le occorrenze della schedulazione nello Storage Account e gestisce anche i riavvii dell'host.
