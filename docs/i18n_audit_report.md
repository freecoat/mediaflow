# i18n Audit Report — v3.5.0-alpha.172.106

**Totale stringhe italiane hardcoded NON coperte da i18n**: 477
**File con findings**: 40
**Lingue target**: it (sorgente), en, fr, de, es

## Top 30 file per count

| File | Count | Esempi |
| --- | ---: | --- |
| `app\templates\pages\planning.html` | 53 | "Filtri", "Cliente", "Progetto" |
| `app\templates\pages\quotes.html` | 34 | "Ricerca", "Cliente", "Stato" |
| `app\static\js\copilot.js` | 31 | "Crea un booking per … (descriv", "Aggiungi voce listino: color g", "<option value="">(nuova)</opti" |
| `app\templates\pages\cost_report.html` | 30 | "Ricerca", "Cliente", "Bozza" |
| `app\templates\pages\finance.html` | 30 | "Caricamento…", "Bozza", "Inviata" |
| `app\templates\pages\project_detail.html` | 27 | "Progetti", "Quotazioni", "Risorse" |
| `app\templates\pages\suppliers.html` | 25 | "Scaduto", "Ricerca", "Fornitore" |
| `app\templates\pages\settings.html` | 24 | "(opzionale)", "Soglia ore/giorno", "Soglia ore/settimana" |
| `app\static\js\global.js` | 24 | "#2a2320", "#1A1A1A", "#11141a" |
| `app\templates\pages\manuale.html` | 22 | "Quotazioni", "Spedizioni", "Cliente" |
| `app\templates\pages\hr.html` | 20 | "Risorsa", "Caricamento…", "Mese:" |
| `app\templates\pages\job_detail.html` | 19 | "Cliente", "Progetto", "Stato" |
| `app\templates\pages\pricelist.html` | 17 | "€/Giorno", "€/Ora", "Caricamento…" |
| `app\templates\pages\physical_assets.html` | 10 | "Caricamento…", "es. WD42-A1B2C3", "Nuovo" |
| `app\templates\pages\client_works.html` | 8 | "Clienti", "Caricamento…", "Elimina" |
| `app\templates\pages\resources.html` | 8 | "Ferie / anno (giorni)", "ROL / mese (ore)", "Permessi / mese (ore)" |
| `app\templates\pages\admin_roles.html` | 7 | "Caricamento…", "Built-in", "Elimina" |
| `app\templates\pages\assets_inout.html` | 7 | "Stato", "Caricamento…", "Caricamento…" |
| `app\templates\pages\dashboard.html` | 7 | "Risorsa", "Caricamento…", "Caricamento…" |
| `app\templates\pages\holidays.html` | 7 | "Risorsa", "Scope: policy CCNL (opzionale)", "Annulla" |
| `app\templates\pages\overhead.html` | 7 | "Caricamento…", "Caricamento…", "Totale" |
| `app\templates\pages\platform_tenants.html` | 7 | "Progetti", "Clienti", "Stato" |
| `app\templates\pages\dam.html` | 6 | "Caricamento…", "Annulla", "Carica" |
| `app\static\js\action_log.js` | 6 | "height:min(420px, 60vh); backg", "+ (e.url ||", "#94a3b8" |
| `app\templates\pages\cashflow.html` | 4 | "Cliente", "Progetto", "Caricamento…" |
| `app\templates\pages\delivery_templates.html` | 4 | "caricamento…", "Caricamento…", "Annulla" |
| `app\templates\pages\team.html` | 4 | "Caricamento…", "Ricerca", "Stato" |
| `app\templates\components\notifications.html` | 3 | "Caricamento…", "Caricamento…", "Errore: '+(e.message||'')+'" |
| `app\templates\pages\admin_users.html` | 3 | "Caricamento…", "Annulla", "Salva" |
| `app\templates\pages\departments.html` | 3 | "Elimina", "Annulla", "Annulla" |

## Findings per file (top 15 file, dettaglio)

### `app\templates\pages\planning.html` (53 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 219 | text | `Filtri` | `planning.filtri` |
| 239 | text | `Cliente` | `planning.cliente` |
| 248 | text | `Progetto` | `planning.progetto` |
| 268 | text | `Lavorazione` | `planning.lavorazione` |
| 277 | text | `Risorsa` | `planning.risorsa` |
| 290 | text | `Confermato` | `planning.confermato` |
| 292 | text | `Fatto` | `planning.fatto` |
| 324 | text | `Progetto` | `planning.progetto` |
| 432 | text | `Caricamento…` | `planning.caricamento` |
| 446 | text | `Caricamento…` | `planning.caricamento` |
| 451 | text | `Caricamento…` | `planning.caricamento` |
| 480 | text | `Progetto` | `planning.progetto` |
| 498 | text | `Giorno` | `planning.giorno` |
| 499 | text | `Settimana` | `planning.settimana` |
| 500 | text | `Mese` | `planning.mese` |
| 779 | text | `caricamento…` | `planning.caricamento` |
| 789 | text | `Caricamento…` | `planning.caricamento` |
| 819 | text | `Annulla` | `planning.annulla` |
| 839 | text | `Risorse` | `planning.risorse` |
| 896 | text | `Quotazione` | `planning.quotazione` |
| ... | ... | (33 altre stringhe) | ... |

### `app\templates\pages\quotes.html` (34 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 160 | text | `Ricerca` | `quotes.ricerca` |
| 164 | text | `Cliente` | `quotes.cliente` |
| 168 | text | `Stato` | `quotes.stato` |
| 171 | text | `Bozza` | `quotes.bozza` |
| 172 | text | `Inviata` | `quotes.inviata` |
| 173 | text | `Approvata` | `quotes.approvata` |
| 174 | text | `Rifiutata` | `quotes.rifiutata` |
| 175 | text | `Scaduta` | `quotes.scaduta` |
| 205 | text | `Caricamento…` | `quotes.caricamento` |
| 451 | text | `Approvata` | `quotes.approvata` |
| 588 | text | `Giorni dopo l'ancora` | `quotes.giorni_dopo_lancora` |
| 590 | text | `0 = subito all'ancora.` | `quotes.0_subito_allancora` |
| 606 | text | `Allocazione a voci di quote (opzionale)` | `quotes.allocazione_a_voci_di_qu` |
| 617 | text | `Annulla` | `quotes.annulla` |
| 731 | text | `hr (ora)` | `quotes.hr_ora` |
| 799 | text | `Annulla` | `quotes.annulla` |
| 825 | text | `Annulla` | `quotes.annulla` |
| 854 | text | `Annulla` | `quotes.annulla` |
| 896 | text | `Annulla` | `quotes.annulla` |
| 897 | text | `Crea` | `quotes.crea` |
| ... | ... | (14 altre stringhe) | ... |

### `app\static\js\copilot.js` (31 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 60 | js_string | `Crea un booking per … (descrivi job/risorsa/quando)` | `copilot.crea_un_booking_per_desc` |
| 91 | js_string | `Aggiungi voce listino: color grading 4K HDR, €1500/giorno` | `copilot.aggiungi_voce_listino_co` |
| 134 | js_string | `<option value="">(nuova)</option>` | `copilot.option_valuenuovaoption` |
| 290 | js_string | `Errore:` | `copilot.errore` |
| 309 | js_string | `Invia` | `copilot.invia` |
| 326 | js_string | `$1<i>$2</i>` | `copilot.1i2i` |
| 333 | js_string | `Cliente (nuovo)` | `copilot.cliente_nuovo` |
| 334 | js_string | `Progetto (nuovo)` | `copilot.progetto_nuovo` |
| 336 | js_string | `Quote (nuova)` | `copilot.quote_nuova` |
| 337 | js_string | `Quote (modifica)` | `copilot.quote_modifica` |
| 341 | js_string | `Risorsa (nuova)` | `copilot.risorsa_nuova` |
| 342 | js_string | `Booking (nuovo)` | `copilot.booking_nuovo` |
| 393 | js_string | `copilotApply(${a.id})` | `copilot.copilotapplyaid` |
| 398 | js_string | `${a.id}` | `copilot.aid` |
| 405 | js_string | `cp-action-data` | `copilot.cpactiondata` |
| 497 | js_string | `Cliente: ${escapeHtml(d.client_name)}` | `copilot.cliente_escapehtmldclien` |
| 569 | js_string | `#${a.resource_id}` | `copilot.aresource_id` |
| 572 | js_string | `<div>• <b>${escapeHtml(who)}</b> · ${escapeHtml(s)} → ${escapeHtml(e)}</div>` | `copilot.div_bescapehtmlwhob_esca` |
| 591 | js_string | `Nuova data inizio: <b>${escapeHtml(d.new_start_date)}</b>` | `copilot.nuova_data_inizio_bescap` |
| 621 | js_string | `Progetto: <b>#${d.project_id}</b>` | `copilot.progetto_bdproject_idb` |
| ... | ... | (11 altre stringhe) | ... |

### `app\templates\pages\cost_report.html` (30 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 17 | text | `Ricerca` | `cost_report.ricerca` |
| 21 | text | `Cliente` | `cost_report.cliente` |
| 29 | text | `Bozza` | `cost_report.bozza` |
| 31 | text | `Approvato` | `cost_report.approvato` |
| 32 | text | `Attivo` | `cost_report.attivo` |
| 36 | text | `Annullato` | `cost_report.annullato` |
| 226 | text | `Stato` | `cost_report.stato` |
| 295 | text | `Caricamento...` | `cost_report.caricamento` |
| 314 | text | `Caricamento…` | `cost_report.caricamento` |
| 355 | text | `Annulla` | `cost_report.annulla` |
| 356 | text | `Salva` | `cost_report.salva` |
| 385 | text | `Annulla` | `cost_report.annulla` |
| 432 | text | `Annulla` | `cost_report.annulla` |
| 485 | text | `Annulla` | `cost_report.annulla` |
| 674 | attr:title | `${r.fake_billing_count} voce(i) di costo con stato fatturato ma 0 ore maturate —` | `cost_report.title.rfake_billing_count_voce` |
| 1146 | text | `Risorsa` | `cost_report.risorsa` |
| 1195 | text | `Quando` | `cost_report.quando` |
| 1196 | text | `Risorse` | `cost_report.risorse` |
| 1197 | text | `Lavorazione` | `cost_report.lavorazione` |
| 1198 | text | `Ore` | `cost_report.ore` |
| ... | ... | (10 altre stringhe) | ... |

### `app\templates\pages\finance.html` (30 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 78 | text | `Caricamento…` | `finance.caricamento` |
| 88 | text | `Bozza` | `finance.bozza` |
| 89 | text | `Inviata` | `finance.inviata` |
| 103 | attr:title | `Mostra fatture in stato 'annullato' (stornate via NC TD04).` | `finance.title.mostra_fatture_in_stato_` |
| 132 | text | `Caricamento…` | `finance.caricamento` |
| 179 | text | `Caricamento…` | `finance.caricamento` |
| 203 | text | `📅 Extra post-fattura` | `finance.extra_postfattura` |
| 232 | text | `Stato:` | `finance.stato` |
| 240 | text | `📅 Extra post-fattura` | `finance.extra_postfattura` |
| 252 | text | `Cliente:` | `finance.cliente` |
| 256 | text | `Progetto:` | `finance.progetto` |
| 295 | attr:placeholder | `Nota (opzionale)` | `finance.placeholder.nota_opzionale` |
| 319 | text | `Caricamento…` | `finance.caricamento` |
| 449 | text | `Annulla` | `finance.annulla` |
| 477 | text | `Progetto` | `finance.progetto` |
| 484 | text | `Quotazione` | `finance.quotazione` |
| 492 | text | `Job (lavorazione)` | `finance.job_lavorazione` |
| 529 | text | `⚠ Forza fattura senza progetto/quotazione` | `finance.forza_fattura_senza_prog` |
| 538 | text | `Annulla` | `finance.annulla` |
| 611 | text | `Annulla` | `finance.annulla` |
| ... | ... | (10 altre stringhe) | ... |

### `app\templates\pages\project_detail.html` (27 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 5 | text | `Progetti` | `project_detail.progetti` |
| 40 | text | `Quotazioni` | `project_detail.quotazioni` |
| 43 | text | `Risorse` | `project_detail.risorse` |
| 58 | text | `Data` | `project_detail.data` |
| 60 | text | `Totale` | `project_detail.totale` |
| 60 | text | `Stato` | `project_detail.stato` |
| 82 | text | `Quotazione` | `project_detail.quotazione` |
| 82 | text | `Voci` | `project_detail.voci` |
| 82 | text | `Stato` | `project_detail.stato` |
| 149 | text | `Data` | `project_detail.data` |
| 151 | text | `Stato` | `project_detail.stato` |
| 156 | text | `Caricamento…` | `project_detail.caricamento` |
| 229 | text | `Annulla` | `project_detail.annulla` |
| 246 | text | `Stato` | `project_detail.stato` |
| 442 | text | `Salvato.` | `project_detail.salvato` |
| 485 | text | `Annulla` | `project_detail.annulla` |
| 534 | text | `Annulla` | `project_detail.annulla` |
| 573 | text | `Annulla` | `project_detail.annulla` |
| 593 | text | `Stato` | `project_detail.stato` |
| 597 | text | `Attivo` | `project_detail.attivo` |
| ... | ... | (7 altre stringhe) | ... |

### `app\templates\pages\suppliers.html` (25 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 19 | text | `Scaduto` | `suppliers.scaduto` |
| 46 | text | `Ricerca` | `suppliers.ricerca` |
| 50 | text | `Fornitore` | `suppliers.fornitore` |
| 56 | text | `Stato` | `suppliers.stato` |
| 90 | text | `Caricamento...` | `suppliers.caricamento` |
| 110 | text | `Caricamento...` | `suppliers.caricamento` |
| 180 | text | `Risorse` | `suppliers.risorse` |
| 189 | text | `Elimina` | `suppliers.elimina` |
| 190 | text | `Annulla` | `suppliers.annulla` |
| 191 | text | `Salva` | `suppliers.salva` |
| 220 | text | `Fornitore` | `suppliers.fornitore` |
| 249 | text | `Totale` | `suppliers.totale` |
| 262 | text | `Annulla` | `suppliers.annulla` |
| 324 | text | `Stato` | `suppliers.stato` |
| 336 | text | `Progetto` | `suppliers.progetto` |
| 389 | text | `Importo` | `suppliers.importo` |
| 393 | text | `Data` | `suppliers.data` |
| 405 | text | `Elimina` | `suppliers.elimina` |
| 406 | text | `Annulla` | `suppliers.annulla` |
| 407 | text | `Salva` | `suppliers.salva` |
| ... | ... | (5 altre stringhe) | ... |

### `app\templates\pages\settings.html` (24 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 268 | text | `(opzionale)` | `settings.opzionale` |
| 311 | text | `Soglia ore/giorno` | `settings.soglia_oregiorno` |
| 316 | text | `Soglia ore/settimana` | `settings.soglia_oresettimana` |
| 358 | text | `(opzionale, per CCNL con maggiorazioni a fasce)` | `settings.opzionale_per_ccnl_con_m` |
| 379 | text | `Ferie maturate / anno (giorni)` | `settings.ferie_maturate_anno_gior` |
| 384 | text | `ROL maturate / mese (ore)` | `settings.rol_maturate_mese_ore` |
| 386 | text | `Default 8h/mese. Riduzione orario di lavoro.` | `settings.default_8hmese_riduzione` |
| 389 | text | `Permessi retribuiti / mese (ore)` | `settings.permessi_retribuiti_mese` |
| 391 | text | `Default 8h/mese. Permessi extra (visite mediche, eventi famigliari, ecc).` | `settings.default_8hmese_permessi_` |
| 398 | text | `Salva` | `settings.salva` |
| 449 | text | `Caricamento…` | `settings.caricamento` |
| 470 | text | `Valore (salvato) *` | `settings.valore_salvato` |
| 485 | text | `Annulla` | `settings.annulla` |
| 486 | text | `Salva` | `settings.salva` |
| 620 | text | `Codice destinatario SDI proprio (opzionale)` | `settings.codice_destinatario_sdi_` |
| 629 | text | `Termini pagamento default (giorni)` | `settings.termini_pagamento_defaul` |
| 675 | text | `Intestazione documento (opzionale)` | `settings.intestazione_documento_o` |
| 724 | text | `scope per-progetto` | `settings.scope_perprogetto` |
| 816 | text | `Annulla` | `settings.annulla` |
| 857 | text | `Record soft-deleted (clienti, progetti, quote, voci listino).` | `settings.record_softdeleted_clien` |
| ... | ... | (4 altre stringhe) | ... |

### `app\static\js\global.js` (24 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 25 | js_string | `#2a2320` | `global.2a2320` |
| 26 | js_string | `#1A1A1A` | `global.1a1a1a` |
| 27 | js_string | `#11141a` | `global.11141a` |
| 28 | js_string | `#1a261f` | `global.1a261f` |
| 31 | js_string | `#2a221b` | `global.2a221b` |
| 32 | js_string | `#1c2a1c` | `global.1c2a1c` |
| 33 | js_string | `#0a0d1a` | `global.0a0d1a` |
| 34 | js_string | `#1a1310` | `global.1a1310` |
| 35 | js_string | `#14101a` | `global.14101a` |
| 36 | js_string | `#0a1418` | `global.0a1418` |
| 38 | js_string | `#2a2a30` | `global.2a2a30` |
| 86 | js_string | `data-theme-id` | `global.datathemeid` |
| 174 | js_string | `data-zoom` | `global.datazoom` |
| 182 | js_string | `: (o.v <= 1.2 ?` | `global.ov_12` |
| 742 | js_string | `Bozza` | `global.bozza` |
| 742 | js_string | `Attivo` | `global.attivo` |
| 743 | js_string | `Annullato` | `global.annullato` |
| 744 | js_string | `Confermato` | `global.confermato` |
| 745 | js_string | `Inviata` | `global.inviata` |
| 745 | js_string | `Scaduta` | `global.scaduta` |
| ... | ... | (4 altre stringhe) | ... |

### `app\templates\pages\manuale.html` (22 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 165 | text | `Quotazioni` | `manuale.quotazioni` |
| 172 | text | `Spedizioni` | `manuale.spedizioni` |
| 216 | text | `Cliente` | `manuale.cliente` |
| 216 | text | `Clienti` | `manuale.clienti` |
| 217 | text | `Progetto` | `manuale.progetto` |
| 217 | text | `Progetti` | `manuale.progetti` |
| 218 | text | `Quotazione` | `manuale.quotazione` |
| 235 | text | `multi-risorsa` | `manuale.multirisorsa` |
| 244 | text | `(Department) — unità di responsabilità trasversale (DI/Video, VFX, Audio, Commer` | `manuale.department_unità_di_resp` |
| 246 | text | `Risorsa` | `manuale.risorsa` |
| 287 | text | `Quotazioni` | `manuale.quotazioni` |
| 288 | text | `Quotazioni` | `manuale.quotazioni` |
| 318 | text | `: rileva da URL su che entità stai lavorando (cliente, progetto, quote, job).` | `manuale.rileva_da_url_su_che_ent` |
| 341 | text | `nel drawer con riassunto leggibile + pulsanti "Applica" / "Rifiuta". L'azione vi` | `manuale.nel_drawer_con_riassunto` |
| 433 | text | `Progetti:` | `manuale.progetti` |
| 437 | text | `Clienti:` | `manuale.clienti` |
| 502 | text | `: tabella con KPI users/progetti/clienti` | `manuale.tabella_con_kpi_userspro` |
| 533 | text | `creato).` | `manuale.creato` |
| 554 | text | `Opt-in:` | `manuale.optin` |
| 600 | text | `"Rifiuta" la card di conferma (l'azione non viene applicata)` | `manuale.rifiuta_la_card_di_confe` |
| ... | ... | (2 altre stringhe) | ... |

### `app\templates\pages\hr.html` (20 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 138 | text | `Risorsa` | `hr.risorsa` |
| 173 | text | `Caricamento…` | `hr.caricamento` |
| 204 | text | `Mese:` | `hr.mese` |
| 220 | attr:title | `Dal` | `hr.title.dal` |
| 238 | text | `XLSX include 2 fogli (Dettaglio + Totali per Risorsa×Mese×Tipo). Range default =` | `hr.xlsx_include_2_fogli_det` |
| 256 | text | `Dal` | `hr.dal` |
| 265 | text | `Caricamento…` | `hr.caricamento` |
| 284 | text | `Caricamento…` | `hr.caricamento` |
| 315 | text | `Settimana` | `hr.settimana` |
| 316 | text | `Mese` | `hr.mese` |
| 328 | text | `Caricamento…` | `hr.caricamento` |
| 373 | text | `Caricamento…` | `hr.caricamento` |
| 465 | text | `Annulla` | `hr.annulla` |
| 466 | text | `Elimina` | `hr.elimina` |
| 467 | text | `Salva` | `hr.salva` |
| 1020 | text | `Errore` | `hr.errore` |
| 1208 | text | `Rifiuta` | `hr.rifiuta` |
| 1214 | text | `Errore: ' + (e.message\|\|'') + '` | `hr.errore_emessage` |
| 1344 | attr:title | `${isPending ? 'Annulla richiesta' : 'Elimina'}` | `hr.title.ispending_annulla_richie` |
| 1516 | text | `Risorsa` | `hr.risorsa` |

### `app\templates\pages\job_detail.html` (19 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 73 | text | `Cliente` | `job_detail.cliente` |
| 77 | text | `Progetto` | `job_detail.progetto` |
| 85 | text | `Stato` | `job_detail.stato` |
| 125 | text | `Lavorazioni` | `job_detail.lavorazioni` |
| 142 | text | `Caricamento…` | `job_detail.caricamento` |
| 152 | text | `Consegne` | `job_detail.consegne` |
| 170 | text | `Caricamento…` | `job_detail.caricamento` |
| 203 | text | `(opzionale)` | `job_detail.opzionale` |
| 209 | text | `(opzionale)` | `job_detail.opzionale` |
| 221 | text | `Annulla` | `job_detail.annulla` |
| 295 | text | `Annulla` | `job_detail.annulla` |
| 343 | text | `Annulla` | `job_detail.annulla` |
| 344 | text | `Aggiungi` | `job_detail.aggiungi` |
| 382 | text | `Caricamento…` | `job_detail.caricamento` |
| 435 | text | `Annulla` | `job_detail.annulla` |
| 436 | text | `Elimina` | `job_detail.elimina` |
| 437 | text | `Salva` | `job_detail.salva` |
| 582 | text | `Caricamento…` | `job_detail.caricamento` |
| 906 | attr:title | `Elimina` | `job_detail.title.elimina` |

### `app\templates\pages\pricelist.html` (17 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 42 | text | `€/Giorno` | `pricelist.giorno` |
| 43 | text | `€/Ora` | `pricelist.ora` |
| 61 | text | `Caricamento…` | `pricelist.caricamento` |
| 83 | text | `Annulla` | `pricelist.annulla` |
| 84 | text | `Crea` | `pricelist.crea` |
| 106 | text | `Annulla` | `pricelist.annulla` |
| 130 | text | `Preset built-in` | `pricelist.preset_builtin` |
| 152 | text | `Caricamento…` | `pricelist.caricamento` |
| 171 | text | `Descrizione (opzionale)` | `pricelist.descrizione_opzionale` |
| 175 | text | `Annulla` | `pricelist.annulla` |
| 196 | text | `auto-salvato` | `pricelist.autosalvato` |
| 200 | text | `Annulla` | `pricelist.annulla` |
| 232 | text | `Annulla` | `pricelist.annulla` |
| 315 | text | `Annulla` | `pricelist.annulla` |
| 316 | text | `Salva` | `pricelist.salva` |
| 652 | text | `Caricamento…` | `pricelist.caricamento` |
| 795 | text | `Caricamento…` | `pricelist.caricamento` |

### `app\templates\pages\physical_assets.html` (10 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 66 | text | `Caricamento…` | `physical_assets.caricamento` |
| 95 | attr:placeholder | `es. WD42-A1B2C3` | `physical_assets.placeholder.es_wd42a1b2c3` |
| 111 | text | `Nuovo` | `physical_assets.nuovo` |
| 186 | text | `Annulla` | `physical_assets.annulla` |
| 251 | text | `Annulla` | `physical_assets.annulla` |
| 280 | text | `Annulla` | `physical_assets.annulla` |
| 317 | text | `Data` | `physical_assets.data` |
| 366 | text | `Annulla` | `physical_assets.annulla` |
| 401 | text | `Caricamento…` | `physical_assets.caricamento` |
| 424 | attr:title | `Consegnato a ${a.delivered_to\|\|'cliente'}` | `physical_assets.title.consegnato_a_adelivered_` |

### `app\templates\pages\client_works.html` (8 stringhe)

| Line | Kind | Text | Suggested key |
| ---: | --- | --- | --- |
| 5 | text | `Clienti` | `client_works.clienti` |
| 50 | text | `Caricamento…` | `client_works.caricamento` |
| 156 | text | `Elimina` | `client_works.elimina` |
| 157 | text | `Annulla` | `client_works.annulla` |
| 158 | text | `Salva` | `client_works.salva` |
| 176 | text | `Annulla` | `client_works.annulla` |
| 201 | text | `Annulla` | `client_works.annulla` |
| 288 | text | `Caricamento…` | `client_works.caricamento` |

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
