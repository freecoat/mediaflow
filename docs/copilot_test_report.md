# Copilot E2E Test Report

_Generato 2026-05-12T10:44:19_

Provider: **Claude (claude-sonnet-4-6)** model `claude-sonnet-4-6`

Ping API: OK ✓

## Test 1 — Filmografie clienti

### Studios Vitali LLC (London)
**Q:** Riassumi in 3-4 righe il cliente 'Studios Vitali LLC' (sede: London, Regno Unito). Dimmi se vedi pattern interessanti nella sua filmografia: Soglia lontano (2017), Mirror (2018), Silence of River (2025), Time (2017), Vento (2020)

**A:** Studios Vitali LLC non è presente nel DB MediaFlow (non compare nella lista CLIENTI ESISTENTI). Non ho quindi dati interni su quote, progetti o storico fatturato.

---

**Profilo sintetico da filmografia dichiarata:**

Studios Vitali LLC è una casa di produzione con sede a Londra, attiva almeno dal 2017. Il catalogo copre un arco di circa 8 anni (2017–2025) con 5 titoli noti, suggerendo una produzione selettiva — **1 titolo ogni 1-2 anni** — tipica di una realtà mid-size orientata alla qualità piuttosto che al volume.

---

**Pattern nella filmografia:**

- **Titoli evocativi / astratti** — *S

### Media Path S.a.s. (Palermo)
**Q:** Riassumi in 3-4 righe il cliente 'Media Path S.a.s.' (sede: Palermo, Italia). Dimmi se vedi pattern interessanti nella sua filmografia: Pane (2026), Voce (2022), Luce (2026), Sabbia (2023), Cielo (2026)

**A:** **Media Path S.a.s.** è una casa di produzione con sede a **Palermo, Italia**, attiva almeno dal 2022. La sua filmografia mostra una produzione costante con titoli brevi e evocativi — tutti sostantivi singoli (Pane, Voce, Luce, Sabbia, Cielo) — che suggerisce una poetica minimalista e un'identità autoriale coerente.

**Pattern rilevanti:**

- **Accelerazione produttiva**: 1 titolo nel 2022, 1 nel 2023, poi **3 titoli nel solo 2026** — segnale di crescita o di un accordo quadro con un distributore/piattaforma.
- **Titoli monosillabici/bisillabici**: tutti i titoli sono sostantivi elementari leg

### Atlas Bruno Ltd (Paris)
**Q:** Riassumi in 3-4 righe il cliente 'Atlas Bruno Ltd' (sede: Paris, Francia). Dimmi se vedi pattern interessanti nella sua filmografia: Tempo (2021), Pane infinito (2016), Pioggia (2016), Path of Horizon (2016), Acqua (2018)

**A:** **Atlas Bruno Ltd** — casa di produzione con sede a Parigi, Francia. Presente in DB con id 97. Filmografia di 5 titoli tra il 2016 e il 2021, tutti in lingua italiana o con titoli italiani (eccetto *Path of Horizon*), suggerendo una forte vocazione per co-produzioni franco-italiane o produzioni destinate al mercato italiano.

**Pattern rilevanti:**

- **Cluster 2016 × 3 titoli** (*Pane infinito*, *Pioggia*, *Path of Horizon*): anno di picco produttivo, probabilmente legato a un periodo di finanziamento o a un accordo di slate.
- **Tematiche naturali/elementali**: *Pioggia*, *Acqua*, *Tempo*, *

## Test 2 — Progetti con quote

### P-2024-0040 — Path of Shadow
**Q:** Per il progetto 'Path of Shadow' (codice P-2024-0040, tipologia corporate, deliverable 4K UHD SDR Rec.709), riassumi in 4 righe il quadro: durata, formato, deadline. Suggerisci 2 voci chiave del listino tipiche.

**A:** ## Path of Shadow — Quadro sintetico

**Durata:** 12,93 min | **Frame rate:** 30 fps | **Formato ripresa:** Sony FX9 XAVC-I | **Consegna:** 4K UHD SDR Rec.709
**Tipologia:** Corporate | **Cliente:** Polaris Lumen S.a.s. | **Regista:** Luca Guadagnino
**Deadline:** 21 novembre 2024 ⚠️ — job già scaduto da 537 giorni (attenzione allo stato del job critico)
**Stato progetto:** Attivo

---

## 2 voci listino consigliate

| # | ID | Voce | Categoria | Tariffa |
|---|-----|------|-----------|---------|
| 1 | **4** | Color grading SDR | PICTURE / DI | €1.650/giorno |
| 2 | **10** | Master ProRes 4444

### P-2025-0020 — Light of Silence
**Q:** Per il progetto 'Light of Silence' (codice P-2025-0020, tipologia corporate, deliverable DPP AS-11 UHD), riassumi in 4 righe il quadro: durata, formato, deadline. Suggerisci 2 voci chiave del listino tipiche.

**A:** ## Light of Silence — Quadro rapido

**Durata:** 8 min 10 sec (8.16 min) | **Frame rate:** 23.976 fps
**Formato ripresa:** Canon C500 Mark II RAW | **Consegna:** DPP AS-11 UHD
**Deadline:** 22 gennaio 2026 | **Stato:** Completato
**Cliente:** Pictures Bruno S.r.l.s. | **Regista:** Park Chan-wook

---

## 2 voci listino chiave per questo progetto

| # | Voce | Categoria | Tariffa | Perché |
|---|------|-----------|---------|--------|
| **id 3** | Online conform | PICTURE / DI | €1.000/giorno | Necessario per allineare il materiale RAW C500 all'EDL/AAF prima della consegna broadcast |
| **id 14*

### P-2025-0004 — Pioggia
**Q:** Per il progetto 'Pioggia' (codice P-2025-0004, tipologia short_film, deliverable HD 1080p25 ProRes), riassumi in 4 righe il quadro: durata, formato, deadline. Suggerisci 2 voci chiave del listino tipiche.

**A:** ## Progetto Pioggia — P-2025-0004

**Durata:** 14 min 21 sec · **Frame rate:** 24 fps
**Formato ripresa:** Sony FX9 XAVC-I · **Consegna:** HD 1080p25 ProRes
**Tipologia:** Short film · **Cliente:** Group Sanna S.p.A.
**Deadline:** 25 febbraio 2026 ⚠️ già scaduta di 76 giorni (oggi 12 maggio 2026)

---

### 2 voci listino chiave per questo progetto

| # | Voce | Categoria | Unità | Prezzo listino |
|---|------|-----------|-------|---------------|
| **id 3** | Online conform | PICTURE / DI | giorno | **€ 1.000** |
| **id 10** | Master ProRes 4444 XQ | DELIVERABLES VIDEO | pc | **€ 500** |

**Per

## Test 3 — Pianificazioni (job + bookings)

### 2025-0001 — Vento Cap. 2 — Job
_12 booking, 27 assignments_

**Q:** Per il job 'Vento Cap. 2 — Job' (codice 2025-0001) ci sono 12 booking con 27 assegnazioni e 5 risorse contrattualmente allocate. Periodo 2025-11-14 → 2026-06-07. Dimmi se la pianificazione sembra ben distribuita o se vedi rischi.

**A:** Ecco la mia lettura della situazione, incrociando i dati disponibili:

---

## 📊 Analisi pianificazione — Vento Cap. 2 (P-2025-0003)

### Stato finanziario
| Voce | Valore |
|---|---|
| Quotato | €99.495 |
| Maturato | €95.011 |
| Atteso a finire | €99.761 |
| Margine | **-€266** (quasi in pareggio) |
| Fatturato | €112.473 |
| Incassato | €57.361 |
| Da incassare | **€55.112** |

> ⚠️ Il maturato (€95k) è già al **95% del quotato** con ancora 26 giorni alla deadline. Lo scostamento atteso è -€266: il progetto è **sostanzialmente a budget**, ma senza margine di sicurezza.

---

### Rischi iden

### 2024-0009 — Fuoco ultimo — Job
_14 booking, 37 assignments_

**Q:** Per il job 'Fuoco ultimo — Job' (codice 2024-0009) ci sono 14 booking con 37 assegnazioni e 6 risorse contrattualmente allocate. Periodo 2024-10-29 → 2025-06-13. Dimmi se la pianificazione sembra ben distribuita o se vedi rischi.

**A:** Ecco l'analisi della pianificazione per **Fuoco ultimo — Job (2024-0009)**. I dati che seguono combinano quanto visibile nel contesto e i risultati del conflict check globale.

---

## 📊 Quadro generale

| Parametro | Valore |
|---|---|
| Periodo | 2024-10-29 → 2025-06-13 |
| Booking | 14 |
| Assegnazioni | 37 |
| Risorse contrattualizzate | 6 |
| Deadline | **2025-06-13** (già scaduta di 333gg rispetto al 2026-05-12 di oggi) |

> ⚠️ **Attenzione critica**: la deadline del job risulta **2025-06-13**, ovvero **333 giorni nel passato**. Il sistema la segnala come 🔴 critica. Se il progetto è anco

### 2024-0015 — Time of Time Stagione 2 — Job
_15 booking, 42 assignments_

**Q:** Per il job 'Time of Time Stagione 2 — Job' (codice 2024-0015) ci sono 15 booking con 42 assegnazioni e 5 risorse contrattualmente allocate. Periodo 2024-12-04 → 2025-04-03. Dimmi se la pianificazione sembra ben distribuita o se vedi rischi.

**A:** Ecco la mia lettura della situazione, incrociando i dati disponibili:

---

## 📊 Analisi pianificazione — Time of Time Stagione 2

### Stato finanziario (punto di partenza)
| Voce | Valore |
|---|---|
| Quotato | €41.046 |
| Maturato (accrued) | €38.423 |
| Atteso a finire | €40.345 |
| Margine residuo | **€701** |
| Fatturato / Incassato | €50.034 / €50.034 ✅ |

> Il progetto è **completato e interamente incassato** — ottimo. Il maturato è al 93,6% del quotato, con uno scostamento positivo di €701 (sotto budget di circa 1,7%).

---

### Valutazione distribuzione pianificazione

**Dati struttu

## Riepilogo entità testate

| Categoria | Nome | Note |
|-----------|------|------|
| Cliente | Studios Vitali LLC | London |
| Cliente | Media Path S.a.s. | Palermo |
| Cliente | Atlas Bruno Ltd | Paris |
| Progetto | Path of Shadow | P-2024-0040 |
| Progetto | Light of Silence | P-2025-0020 |
| Progetto | Pioggia | P-2025-0004 |
| Planning (Job) | Vento Cap. 2 — Job | 2025-0001 — 12 booking |
| Planning (Job) | Fuoco ultimo — Job | 2024-0009 — 14 booking |
| Planning (Job) | Time of Time Stagione 2 — Job | 2024-0015 — 15 booking |