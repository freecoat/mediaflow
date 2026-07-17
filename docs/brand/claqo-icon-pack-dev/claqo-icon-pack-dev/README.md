# Claqo Icon Pack — Dev / Variants

Pacchetto delle **4 varianti logo** mostrate nella prima fase di sviluppo brand, isolate per uso designer.
Equivalente al "Classic" ma con la variante B più ricca (3 dots interni alla slate).

## Contenuto

```
claqo-icon-pack-dev/
├── README.md
├── variants/                  # 4 brand variants (200x200)
│   ├── variant-A-filled.svg       # Default app/social
│   ├── variant-B-outline-dark.svg # Dark UI, sticker (con 3 dots)
│   ├── variant-C-stripe.svg       # Pattern, loading, editorial
│   └── variant-D-monogram.svg     # Watermark, footer compresso
├── app-icon-scale/            # Stessa icona (variante A) a 6 taglie
│   ├── app-icon-16.svg
│   ├── app-icon-32.svg
│   ├── app-icon-64.svg
│   ├── app-icon-128.svg
│   ├── app-icon-256.svg
│   └── app-icon-512.svg
└── palette/
    ├── tokens.json
    ├── tokens.css
    ├── tokens.scss
    └── palette-preview.svg
```

## Quando usare quale variante

| Variante | Sfondo | Uso primario |
|---|---|---|
| **A · filled** | claqo-red | Default — app icon, favicon, avatar social |
| **B · outline dark** | stage-black | UI dark mode, sticker, merchandising |
| **C · stripe** | take-cream | Loading state, illustrazioni editoriali, brand pattern |
| **D · monogram** | white | Watermark, footer, contesti ≤32 px |

## Colori

| Token | Hex |
|---|---|
| `claqo-red`   | `#D85A30` |
| `stage-black` | `#1A1A1A` |
| `take-cream`  | `#FAECE7` |
| `cue-amber`   | `#EF9F27` |
| `studio-grey` | `#5F5E5A` |

---

*Claqo Icon Pack v1.0 — Dev/Variants edition.*
