# Claqo — Brand Brief

> CRM/SaaS per la gestione di studi e progetti di post-produzione audiovisiva.

---

## 1. Nome

**Claqo** — derivato da *claquette / ciak*: il segnale che dà l'inizio al take.
Pronuncia: `KLA-ko`. Cinque lettere. Brandable, scarso rischio di conflitto.

**Disponibilità (verifica preliminare)**
- Nessun SaaS competitor diretto trovato via web search
- Da confermare: USPTO + EUIPO classe 42 (SaaS), WHOIS `claqo.com` / `claqo.io` / `claqo.app`

---

## 2. Posizionamento

**Tagline primaria:** *Action on every project.*
**Alternative IT:** *Dal brief al master, in un ciak.* · *Il backstage del tuo studio.*

**Audience:** studi di post-produzione, color house, sound studio, edit boutique, freelance senior.
**Promessa:** un unico ambiente per pipeline cliente, brief, versioni, deliverables e fatturazione — pensato per il flusso audiovisivo, non adattato da un CRM generico.

---

## 3. Logo & Mascot

### Concept: robot mascot
Claqo è un **robottino-claquette**. L'icona è insieme un personaggio e uno strumento di set: il braccio mobile della claquette diventa il **ciuffo** inclinato del robot, la lavagnetta diventa la **faccia**, gli occhi tondi danno vita al brand.

### Anatomia
```
┌──────────────────────────┐
│   ╱╱╱╱  ciuffo (clapper) │  ← cuneo inclinato con strisce diagonali
│ ┌────────────────────┐    │
│ │   ●    ●   slate   │    │  ← faccia / lavagnetta
│ │      ‿      eyes   │    │
│ └────────────────────┘    │
└──────────────────────────┘
```

| Elemento | Descrizione | Token colore |
|---|---|---|
| Background | Rounded square, radius 22% del lato | `claqo-red` |
| Ciuffo / clapper | Cuneo inclinato +15° con 3 strisce diagonali bianche | `stage-black` + `take-cream` |
| Slate / faccia | Rettangolo arrotondato `r=5%` | `take-cream` |
| Occhi | Due cerchi neri con highlight bianco off-center | `stage-black` + white |
| Bocca (default) | Curva sorridente sottile | `stage-black` stroke 2px |
| Guance (opt.) | Due punti `claqo-red` 50% opacity | — |

### Espressioni
| Variante | Quando usarla |
|---|---|
| **default** (smile) | App icon, splash, marketing |
| **wink** | Conferme di successo, "ciak!" sent confirmations |
| **focus** (occhi a fessura, bocca neutra) | Loading lunghi, render, esportazioni in corso |
| **alert** (occhi spalancati, bocca a O, dot ambra) | Notifiche di review richieste, errori soft |

### Scale & leggibilità
| Size | Note |
|---|---|
| ≥ 64 px | Tutti i dettagli (highlight, guance, bocca) |
| 32–48 px | Rimuovere guance e highlight, mantenere occhi e bocca |
| 24 px | Solo ciuffo + slate + occhi, no bocca |
| 16 px | Versione monogramma — silhouette ciuffo + slate, niente occhi |

### Costruzione tecnica (per implementazione)
- Canvas quadrato, padding interno 14% del lato
- Ciuffo: polygon a 4 punti, inclinazione 15°, occupa il 35% superiore della safe area
- Strisce: 3 trapezi bianchi distribuiti, larghezza ~10% del ciuffo ciascuna
- Slate: rettangolo arrotondato che occupa il 60% inferiore della safe area
- Occhi: cerchi r = 9.5% del lato, centrati a 32% e 68% della larghezza slate, y a 40% dell'altezza slate
- Highlight occhi: piccolo cerchio bianco r = 2.8% del lato, offset +12% in alto a destra rispetto al centro dell'occhio

### Varianti formato
| Codice | Uso |
|---|---|
| A · mascot full color | Default — app icon, favicon, social avatar, splash |
| B · mascot outline dark | UI dark mode, sticker, merchandising |
| C · clapper only (no face) | Loading state pre-personality, brand pattern |
| D · monogram silhouette | Watermark, footer, contesti ≤16px |

### Regole d'uso
- **Mai** ruotare, distorcere o cambiare le proporzioni
- Mai sostituire i colori del ciuffo: bianco/nero sono firma cinematografica
- L'espressione di default è il sorriso. Le altre espressioni sono **contestuali**, non decorative
- Padding minimo attorno al logo = altezza dello slate

---

## 4. Wordmark

- Font: Anthropic Sans (o equivalente geometric sans: Inter, Söhne, Aeonik)
- Peso: 500 (Medium)
- Tracking: −0.5px a corpo grande, 0 a corpo piccolo
- Set: minuscolo sempre (`claqo`, mai `Claqo` o `CLAQO`)

---

## 5. Palette

| Token | Hex | Uso |
|---|---|---|
| `claqo-red` | `#D85A30` | Brand primario, CTA, accenti |
| `stage-black` | `#1A1A1A` | Testo principale, sfondi dark mode |
| `take-cream` | `#FAECE7` | Sfondi soft, surface secondaria, hover light |
| `cue-amber` | `#EF9F27` | Accento secondario, badge, notifiche neutre |
| `studio-grey` | `#5F5E5A` | Testo secondario, divider, metadata |

**Regole d'uso**
- Solo `claqo-red` per le CTA primarie
- `cue-amber` riservato a stati "in attesa di azione" (review needed, draft pending)
- `stage-black` su `take-cream` per blocchi editoriali; mai `claqo-red` su `cue-amber`

---

## 6. Tipografia

| Ruolo | Font | Peso | Size |
|---|---|---|---|
| Display | Anthropic Sans | 500 | 32–72 px |
| Heading | Anthropic Sans | 500 | 18–24 px |
| Body | Anthropic Sans | 400 | 14–16 px |
| Mono (codici progetto, timecode) | JetBrains Mono | 400 | 13–14 px |

Sentence case ovunque. Mai ALL CAPS, mai Title Case.

---

## 7. Tono di voce

**Diretto, professionale, leggero — con la complicità del robottino.** Linguaggio di set, non di marketing. La mascotte permette qualche tocco affettuoso senza scadere nel cute.
- Sì: "Take", "Brief", "Master", "Pipeline", "Dailies", "Round di review"
- No: "Soluzione", "Esperienza", "Engagement", "Sinergia"

**Microcopy esempi**
- Empty state progetti: *Nessun take ancora. Crea il primo brief.*
- Conferma invio: *Inviato al cliente. Aspettiamo il "ciak".*
- Error generico: *Stop. Qualcosa non torna — riprova.*

---

## 8. Tassonomia prodotto (suggerita)

- **Project** → **Production** (un lavoro completo per cliente)
- **Task** → **Take** (singolo deliverable / fase)
- **Lead** → **Brief** (richiesta cliente in ingresso)
- **Customer** → **Studio** o **Client**
- **Stage** del CRM → `Brief → Quote → Production → Review → Master → Invoiced`
- **File** → **Asset** (con sottotipi: rush, edit, color, mix, master)

---

## 9. Asset da produrre (checklist per Claude Code)

- [ ] `favicon.ico` + `apple-touch-icon.png` (180px) + manifest icons (192, 512)
- [ ] Mascot SVG: 4 espressioni (default, wink, focus, alert)
- [ ] Logo SVG: orizzontale (mascot + wordmark), verticale, solo mascot, monogramma silhouette
- [ ] Dark / light variants per ognuno
- [ ] Loader animato — il clapper si chiude, gli occhi fanno wink
- [ ] Empty state illustrations con mascot (no projects, no clients, no invoices, all clear)
- [ ] Sticker pack (Slack / Telegram): 6–8 espressioni
- [ ] Email template header
- [ ] OpenGraph image (1200×630)
- [ ] Cover LinkedIn / X
- [ ] Pitch deck template (16:9)

---

## 10. Componenti UI prioritari

1. **Pipeline board** — kanban orizzontale, una colonna per stage, card con timecode totale e stato cliente
2. **Production view** — dettaglio del lavoro: take list, versioni, asset, review thread, fatture collegate
3. **Brief inbox** — richieste in ingresso con score di priorità
4. **Master library** — archivio deliverables con preview e link condivisibili scadenza
5. **Studio occupancy** — calendar view per allocazione sale/risorse umane

---

## 11. Note legali

Prima del lancio commerciale:
1. Ricerca trademark USPTO ed EUIPO classe 42 (SaaS) e classe 9 (downloadable software)
2. Acquisto domini: `.com` `.io` `.app` `.studio` minimo
3. Account social: handle `@claqo` su Instagram, X, LinkedIn, GitHub
4. Verifica Apple App Store / Google Play naming policy (no conflict con app esistenti)

---

*Brand brief v0.1 — generato come baseline per progetto Claude Code.*
