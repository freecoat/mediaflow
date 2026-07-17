# Claqo Brand Pack

CRM/SaaS per la post-produzione audiovisiva.

## Struttura

```
claqo-brand-pack/
├── BRAND-BRIEF.md          # Brief completo (nome, positioning, tipografia, voce, tassonomia)
├── README.md               # Questo file
├── icons/                  # App icon a varie taglie + favicon
│   ├── app-icon-512.svg
│   ├── app-icon-192.svg    # PWA manifest
│   ├── app-icon-64.svg
│   ├── app-icon-32.svg
│   ├── app-icon-16.svg     # Versione minima (no occhi/bocca)
│   ├── apple-touch-icon.svg
│   ├── favicon.svg
│   └── monogram.svg        # Silhouette nera, sfondo trasparente
├── mascot/                 # Robot mascot, 4 espressioni
│   ├── claqo-default.svg   # Smile — uso default
│   ├── claqo-wink.svg      # Conferme, "ciak!"
│   ├── claqo-focus.svg     # Loading lunghi, render
│   ├── claqo-alert.svg     # Notifiche, review richieste
│   └── claqo-clapper-only.svg  # Solo clapper+slate, no faccia
├── logo/                   # Lockup completi (mascot + wordmark)
│   ├── logo-horizontal.svg
│   ├── logo-horizontal-dark.svg
│   ├── logo-vertical.svg
│   ├── wordmark.svg
│   └── wordmark-dark.svg
└── palette/                # Token colore in JSON, CSS, SCSS
    ├── tokens.json
    ├── tokens.css
    ├── tokens.scss
    └── palette-preview.svg
```

## Quick start

### Import dei token CSS
```css
@import "./palette/tokens.css";

.button-primary {
  background: var(--claqo-red);
  color: var(--take-cream);
  border-radius: var(--radius-lg);
}
```

### Uso del logo in React
```jsx
import logo from "./logo/logo-horizontal.svg";
<img src={logo} alt="Claqo" height={40} />
```

### Mascot dinamico
Usa la variante in base al contesto:

| Stato | File |
|---|---|
| Generico, marketing, vuoto positivo | `claqo-default.svg` |
| Conferma inviata, salvataggio ok | `claqo-wink.svg` |
| Loading > 2s, render, export | `claqo-focus.svg` |
| Notifica review, errore soft | `claqo-alert.svg` |

## Colori — riferimento rapido

| Token | Hex | Uso |
|---|---|---|
| `claqo-red` | `#D85A30` | Brand, CTA |
| `stage-black` | `#1A1A1A` | Testo, dark surface |
| `take-cream` | `#FAECE7` | Surface soft |
| `cue-amber` | `#EF9F27` | Stati in attesa |
| `studio-grey` | `#5F5E5A` | Metadata, divider |

## Tipografia

- **Sans (UI):** Inter (fallback: Helvetica Neue, Arial)
- **Mono (timecode, codici):** JetBrains Mono
- Wordmark: peso 500, tracking -3.5, **sempre minuscolo**

## Regole d'uso (sintesi)

- Mai distorcere o ruotare il mascot
- Mai cambiare il bianco/nero del ciuffo (firma cinema)
- Padding minimo attorno al logo = altezza dello slate
- Solo `claqo-red` per le CTA primarie
- Per il dettaglio completo vedi `BRAND-BRIEF.md`

## Asset ancora da generare

- [ ] PNG raster a partire dagli SVG (per piattaforme che non supportano SVG)
- [ ] `favicon.ico` multi-size
- [ ] Animated SVG loader (clapper che si chiude → wink)
- [ ] Empty-state illustrations
- [ ] Sticker pack (Slack/Telegram)
- [ ] OpenGraph image 1200×630
- [ ] Pitch deck template

---

*Claqo Brand Pack v1.0 — generato per progetto Claude Code.*
