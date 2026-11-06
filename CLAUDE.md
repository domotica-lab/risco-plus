# Risco Plus (integrazione Home Assistant + scheda) - contesto progetto

Rispondi sempre in **italiano**. L'utente non e' uno sviluppatore: istruzioni passo passo,
niente gergo inutile. Mai scrivere nel progetto password, PIN, codici, email, indirizzi,
ID o IP di impianti reali: il progetto e' pensato per essere condiviso.

## Cos'e'
Integrazione **separata** `risco_plus` (da pubblicare su GitHub/HACS), nata dalla copia
dell'integrazione core `risco` di **HA 2026.10.2** (`pyrisco==0.8.1`) con funzioni aggiuntive,
tutte opzionali. Fino alla 2026.10.2.4 era un override del dominio `risco`: le vecchie
opzioni sono ancora lette. Manifest: `version` semver (oggi 1.0.4), `codeowners`/`documentation`/
`issue_tracker` con l'utente GitHub `domotica-lab`.
- `migrate.py` + passo `migrate` del config flow: copia dati/opzioni di una entry `risco`
  (`CONF_MIGRATED_FROM` nei data), al primo avvio disattiva la vecchia entry e sposta
  entity_id/nomi/icone/aree (vecchie entita' rinominate `*_risco_old`), aree dei dispositivi.
- La scheda sta in `custom_components/risco_plus/frontend/risco-plus-card.js`, servita da
  `__init__._async_register_card` (`/risco_plus/risco-plus-card.js?v=<version>`,
  `add_extra_js_url`): nessuna risorsa manuale. La scheda usa il dominio `risco_plus`
  (o `risco` per le vecchie installazioni).
- Valori dei gruppi nei selettori in minuscolo ("bc", per hassfest), salvati in maiuscolo.
- `.github/workflows/validate.yml`: HACS action, hassfest, pytest.
- `.github/workflows/release.yml`: dopo un "Validate" verde su `main`, se la `version` del
  manifest non ha ancora il tag, crea tag `v<version>` e release con l'elenco dei commit
  dall'ultimo tag. **Per pubblicare basta aumentare `version` nel manifest** (semver):
  la sessione di Claude non puo' creare release da se'.

## Struttura
- `custom_components/risco_plus/` - integrazione. File cambiati rispetto al core:
  - `const.py`: costanti Risco Plus (`CONF_CUSTOM_CODE`, `CONF_PERIMETER_ZONES`,
    `CONF_ZONE_GROUPS`, `CONF_CLOUD_CACHE`, `DEFAULT_EXTRA_OPTIONS`, retry 52, pause).
  - `alarm_control_panel.py`: azione `risco_plus.arm_groups` (voluptuous, come nella versione
    provata sul campo), attributo `armed_groups`, tutti i gruppi -> stato di `arm`,
    `_validate_code` (codice personale se impostato, altrimenti PIN; `None` sempre rifiutato),
    codice personale -> disinserimento sempre con codice, `code_format` TEXT se il codice
    ha lettere, `arm_groups` accetta `code` (controllato solo con `code_arm_required`),
    blocco zone aperte (`open_perimeter_zones`, `zone_groups`, `parse_zone_groups`),
    retry su result 52 con `HomeAssistantError(translation_key="panel_busy")`,
    risposta comando senza partizioni -> refresh del coordinator.
  - `coordinator.py`: opzione `read_from_cloud_cache` -> `fromControlPanel: False`
    (stato ed eventi), eventi ogni 120 s in quel caso.
  - `config_flow.py`: sezione opzioni `extra_options` (Optional) con selettori
    (password, multi-select zone dal runtime_data, testo multiriga, booleano).
  - `strings.json`, `translations/en.json` (chiavi risolte), `translations/it.json`,
    `services.yaml` (+ `arm_groups`), `icons.json`.
  - Tutti i `.py` hanno `from __future__ import annotations` (servono ai test su Python 3.13;
    HA 2026.10 usa Python 3.14).
  - `groups.py` (nomi gruppi, `groups_of` per valori "C"/"BC", `armed_groups`),
    `group_entity.py` + `button.py` + fondo di `binary_sensor.py`: entità per gruppo
    (opzione `group_entities`, unique_id `<id allarme>_group_<G>[_arm]`, tolte se l'opzione
    e' spenta). Il pulsante chiama `risco.arm_groups`.
  - Modalita' HA -> piu' gruppi (`ha_states_to_risco` puo' valere "BC"; "none" = non usato,
    non salvato); stato: combinazione esatta -> quella modalita'. Selettori tradotti
    (`selector.ha_state`, `selector.risco_state`).
  - `open_zones_mode` (off / block = tutte le zone dei gruppi / block_selected = solo
    `perimeter_zones` / bypass = esclude le altre), `open_zones_mode()` in const legge anche
    le vecchie opzioni (`perimeter_zones` -> block_selected, `auto_bypass_open_zones` ->
    bypass). Rifiuto -> evento `risco_arming_refused`; esclusione -> evento
    `risco_zones_bypassed`; notifica di HA solo con l'opzione `persistent_notifications` (spenta: basta il messaggio della scheda, l'utente fa le sue notifiche). Sezione `zone_groups_section`: `zones_group_a..d` (id zona per
    gruppo, chiavi "#id" nella mappa di `zone_groups`) + vecchio testo `zone_groups`. Codice errato -> `ServiceValidationError`
    (`invalid_code`), i test di serie sono adattati.
- `custom_components/risco_plus/frontend/risco-plus-card.js` - scheda Lovelace (vanilla JS, shadow DOM, **solo ASCII**,
  testi it/en in `TESTI`). Registra `risco-plus-card` e l'alias `risco-casa-card`.
  Legge `armed_groups` (fallback `gruppi_inseriti`). Il codice usa la finestra
  ORIGINALE di HA (`loadCardHelpers().showEnterCodeDialog`); il tastierino interno e' solo
  riserva: non ridisegnarlo a mano, deve restare identico all'originale.
- `tests/` - test core adattati + `test_plus.py`. `tests/shim/probatio.py` si usa solo se
  `probatio` manca (ambienti HA < 2026.10). Eseguire: `pytest` (63 test).
- `esempi/` - scheda e automazione di controllo (attributo `armed_groups`).

## Cose imparate sul campo (centrale LightSYS 2 con modulo IP RW132IP del 2013)
- Il modulo IP gestisce una connessione alla volta: porta locale 1000 chiusa se c'e' il
  cloud; la lettura in diretta del core (`fromControlPanel: True`) faceva rifiutare l'app
  iRISCO -> da qui l'opzione `read_from_cloud_cache`.
- Dopo un comando, la sessione del cloud blocca per qualche minuto gli altri utenti.
- In Parziale il cloud rifiuta il Totale (la scheda nasconde il pulsante).
- Il cloud di solito non manda i gruppi delle zone -> campo `zone_groups`.
- Configuration Software collegato via cloud blocca tutti i comandi: va chiuso.
- Un account Risco = un impianto (il config flow prende il primo sito).

## Regole per modifiche
- Restare vicini al core: ogni funzione nuova opzionale e con default = comportamento di serie.
- Aggiornare insieme `strings.json` e le due `translations/*.json`.
- Dopo ogni modifica: `pytest`, `node --check custom_components/risco_plus/frontend/risco-plus-card.js`, nessun carattere
  non ASCII nella scheda.
- Prima di allineare a una nuova versione di HA: confrontare i file core della nuova versione
  con questa copia e riportare solo le differenze.

## Da fare / idee
- Verificare sul campo che la copia del cloud segni i sensori aperti (blocco zone).
- Notifica quando una zona viene esclusa all'inserimento da app iRISCO (quella da HA c'e' gia').
- Repository: github.com/domotica-lab/risco-plus. Icona e logo originali in `custom_components/risco_plus/brand/` (icon 256/512, logo e dark_logo 337x128 e @2x 674x256; HA 2026.3+ li legge da li'), stesso stile di domotica-lab/hikvision_axpro_cloud: fondo #293243->#1b2231, scudo bianco, dettaglio rosso #d92d27 (qui 4 quadratini = gruppi, due tonalita'). Non usare il logo Risco (marchio).
