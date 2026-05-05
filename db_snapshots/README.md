# DB Snapshots — porting test

Cartella per snapshot del database SQLite di lavoro, da committare quando
serve verificare il porting su un'altra macchina con dati reali.

I file `*.db` qui sono **eccezioni** al `.gitignore` globale (vedi regola
`!db_snapshots/*.db` in `.gitignore`).

## Convenzione naming

`snapshot-{versione}.db` — es. `snapshot-3.5.0-alpha.23.db`.

## Come ripristinare in locale

1. Backup del db corrente: `mv mediaflow.db mediaflow.db.bak`
2. Copia snapshot: `cp db_snapshots/snapshot-X.db mediaflow.db`
3. Avvia: `./strumenti.sh` opzione [4] (start) — l'auto-migrate al boot
   gestirà eventuali differenze di schema.

## Quando creare uno snapshot

- Prima di un cambio architetturale rilevante (per rollback rapido).
- Quando serve confrontare comportamenti su macchine diverse con stesso DB.
- Prima di un purge del cestino (delete fisico) per archivio.

Non è un sostituto del backup periodico: questi snapshot vivono nel git e
sono visibili a chiunque ha accesso al repo.
