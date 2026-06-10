# Claqo Agent

Demone facility standalone per l'Asset Registry di Claqo (F1).
Gira sulla macchina di facility, NON sul server. Non richiede il codice server.

## Prerequisiti

- Python 3.11+
- `ffprobe` (parte di ffmpeg) nel PATH di sistema
- Accesso ai volumi NAS/locali montati sulla macchina

## Installazione

```bash
# Crea un venv dedicato nella directory dell'agent
python -m venv agent-venv

# Attiva il venv
# macOS/Linux:
source agent-venv/bin/activate
# Windows:
agent-venv\Scripts\activate

# Installa le dipendenze (solo requests + xxhash)
pip install -r agent/requirements.txt
```

## Configurazione

### Ottieni il token

Nell'UI di Claqo vai su `/storage` → tab **Agent** → crea un nuovo agent → copia il token
(visibile una sola volta).

### Opzione A — file `claqo-agent.json` nella directory di lavoro

```json
{
  "server_url": "https://your-claqo-host",
  "token": "il-tuo-token-qui"
}
```

### Opzione B — variabili d'ambiente

| Variabile                  | Descrizione                             | Default |
|----------------------------|-----------------------------------------|---------|
| `CLAQO_URL`                | URL base del server Claqo (obbligatorio) | —      |
| `CLAQO_AGENT_TOKEN`        | Token agent (obbligatorio)              | —       |
| `CLAQO_POLL_SECONDS`       | Intervallo polling coda job             | 5       |
| `CLAQO_HEARTBEAT_SECONDS`  | Intervallo heartbeat                    | 30      |

Esempio:

```bash
export CLAQO_URL=https://your-claqo-host
export CLAQO_AGENT_TOKEN=il-tuo-token-qui
```

## Avvio

```bash
# Dalla root del progetto (con venv attivo):
python -m agent.main
```

## Funzionamento

Il loop dell'agent:

1. **Heartbeat** ogni 30s → registra versione, capabilities, statistiche volumi
2. **Poll** ogni 5s → richiede un job dalla coda
3. **Esegue** il job localmente (probe ffprobe o checksum xxhash)
4. **POST result** → invia solo metadati JSON al server

## Principio di sicurezza

**Nessun byte di contenuto lascia la facility.**

Il server riceve solo:
- Specifiche tecniche ffprobe (codec, risoluzione, frame rate, canali audio…)
- Checksum xxhash64 (16 caratteri hex)
- Dimensione file in byte
- MIME type dedotto dall'estensione

I file audio/video originali restano sul volume di facility.

## Capabilities supportate

| Job type    | Descrizione                                      |
|-------------|--------------------------------------------------|
| `probe`     | Esegue ffprobe + xxhash + size + mime type       |
| `checksum`  | Solo xxhash64 (file già noto, aggiorna checksum) |
