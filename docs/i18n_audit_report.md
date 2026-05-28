# i18n Audit Report — v3.5.0-alpha.172.106

**Totale stringhe italiane hardcoded NON coperte da i18n**: 15
**File con findings**: 6
**Lingue target**: it (sorgente), en, fr, de, es

## Top 30 file per count

| File | Count | Esempi |
| --- | ---: | --- |
| `app\templates\pages\manuale.html` | 7 | "(Department) — unità di respon", ": rileva da URL su che entità ", "nel drawer con riassunto leggi" |
| `app\static\js\global.js` | 3 | ": (o.v <= 1.2 ?", "button[data-t]", "form-input mf-dt-date" |
| `app\static\js\action_log.js` | 2 | "height:min(420px, 60vh); backg", "display:none;margin-top:4px;pa" |
| `app\templates\pages\finance.html` | 1 | "Mostra fatture in stato 'annul" |
| `app\templates\pages\project_detail.html` | 1 | "Cooke Anamorphic/i\nCanon 15.5" |
| `app\static\js\copilot.js` | 1 | ") + (a._error ?" |

## Findings per file (top 15 file, dettaglio)

### `app\templates\pages\manuale.html` (7 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 244 | text | `(Department) — unità di responsabilità trasversale (DI/Video, VFX, Audio, Commer` | `manuale.department_unità_di_resp` |
| 318 | text | `: rileva da URL su che entità stai lavorando (cliente, progetto, quote, job).` | `manuale.rileva_da_url_su_che_ent` |
| 341 | text | `nel drawer con riassunto leggibile + pulsanti "Applica" / "Rifiuta". L'azione vi` | `manuale.nel_drawer_con_riassunto` |
| 502 | text | `: tabella con KPI users/progetti/clienti` | `manuale.tabella_con_kpi_userspro` |
| 533 | text | `creato).` | `manuale.creato` |
| 554 | text | `Opt-in:` | `manuale.optin` |
| 600 | text | `"Rifiuta" la card di conferma (l'azione non viene applicata)` | `manuale.rifiuta_la_card_di_confe` |

### `app\static\js\global.js` (3 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 182 | js_string | `: (o.v <= 1.2 ?` | `global.ov_12` |
| 1484 | js_string | `button[data-t]` | `global.buttondatat` |
| 1535 | js_string | `form-input mf-dt-date` | `global.forminput_mfdtdate` |

### `app\static\js\action_log.js` (2 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 79 | js_string | `height:min(420px, 60vh); background:var(--bg2, #1f2436); color:var(--text1, #e8e` | `action_log.heightmin420px_60vh_back` |
| 207 | js_string | `display:none;margin-top:4px;padding:6px 8px;background:rgba(0,0,0,0.25);border-r` | `action_log.displaynonemargintop4pxp` |

### `app\templates\pages\finance.html` (1 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 104 | attr:title | `Mostra fatture in stato 'annullato' (stornate via NC TD04).` | `finance.title.mostra_fatture_in_stato_` |

### `app\templates\pages\project_detail.html` (1 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 1577 | attr:placeholder | `Cooke Anamorphic/i\nCanon 15.5-45` | `project_detail.placeholder.cooke_anamorphicincanon_` |

### `app\static\js\copilot.js` (1 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 914 | js_string | `) + (a._error ?` | `copilot.a_error` |

## Come procedere

1. **Aggiungi chiave** a `app/static/js/i18n.js` dict `window.MF_I18N`:
   ```js
   'chiave.suggerita': {it: 'Testo italiano', en: 'English', fr: 'Français', de: 'Deutsch', es: 'Español'},
   ```

2. **Annota nel template** la stringa con `data-i18n`:
   ```html
   <span data-i18n="chiave.suggerita">Testo italiano</span>
   ```

3. **Per attributi** (placeholder/title/etc) usa `data-i18n-attr`:
   ```html
   <input data-i18n="chiave.placeholder" data-i18n-attr="placeholder" placeholder="Cerca">
   ```

4. **Per JS toast/prompt** crea helper `t(key, default)`:
   ```js
   toast(t('errors.save_failed', 'Salvataggio fallito'), 'error');
   ```

Re-run audit per verificare gap dopo ogni batch di traduzioni.
