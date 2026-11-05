# Risco Plus per Home Assistant

[![Apri in HACS / Marketplace](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=domotica-lab&repository=risco-plus&category=integration)
[![Aggiungi l'integrazione](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=risco_plus)

[![Versione](https://img.shields.io/github/v/release/domotica-lab/risco-plus)](https://github.com/domotica-lab/risco-plus/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/domotica-lab/risco-plus/actions/workflows/validate.yml/badge.svg)](https://github.com/domotica-lab/risco-plus/actions/workflows/validate.yml)

Integrazione per le centrali di allarme **Risco** (Risco Cloud o collegamento locale),
pensata per chi usa i **gruppi A-D**. Parte dall'integrazione Risco di Home Assistant
(2026.10.2, pyrisco 0.8.1) e aggiunge inserimento di più gruppi, modalità con più gruppi,
controllo delle zone aperte, codice personale e una scheda per la plancia, già inclusa.

È un'integrazione **separata** (`risco_plus`): può stare accanto a quella di serie e, se la
usavi, ne copia account, opzioni e nomi delle entità.

> **English:** Risco alarm integration for Home Assistant focused on groups A-D: arm several
> groups at once, map Home Assistant modes to group combinations (e.g. Night = B + C), refuse
> or bypass open zones (with events for your automations), per-group entities, custom code and a bundled
> dashboard card. It can take over an existing Risco integration keeping entity ids.
> UI in English and Italian.

## Cosa aggiunge rispetto all'integrazione di serie

| Funzione | Dove si attiva | Note |
|---|---|---|
| **Inserimento di più gruppi insieme** (azione `risco_plus.arm_groups`) | sempre attiva | es. gruppi B + C in un solo comando |
| **Modalità con più gruppi** (es. "Attivo notte" = B + C) | Opzioni → ultima schermata | funziona con il pannello allarme di serie, la voce e le automazioni; lo stato mostra la modalità giusta |
| **Attributo `armed_groups`** con i gruppi inseriti | sempre attivo | tutti e 4 i gruppi inseriti = "inserito totale" |
| **Nomi dei gruppi** (es. "B: Balconi") | Opzioni → Risco Plus | usati dalla scheda e dalle entità dei gruppi |
| **Entità per ogni gruppo**: sensore "Gruppo B inserito" e pulsante "Inserisci gruppo B" | Opzioni → Risco Plus | per automazioni, assistenti vocali e plance |
| **Controllo delle zone aperte** all'inserimento | Opzioni → Risco Plus | non inserisce e avvisa (tutte le zone dei gruppi, senza sceglierle), oppure esclude le zone aperte come l'app iRISCO |
| **Codice personale** per inserire/disinserire da HA | Opzioni → Risco Plus | vale **solo** questo codice, non il PIN dell'integrazione |
| **Codice errato**: messaggio immediato | sempre attivo | |
| **Lettura dalla copia di Risco Cloud** | Opzioni → Risco Plus | per moduli IP vecchi: l'app iRISCO non va più in "errore di connessione" |
| **Nuovi tentativi se la centrale è occupata** (Risco Cloud, codice 52) | sempre attiva | 3 tentativi, poi un messaggio chiaro |
| **Scheda per la plancia** inclusa | sempre attiva | si carica da sola, nessuna risorsa da aggiungere |
| **Italiano** in opzioni, menu e messaggi | sempre attivo | |

## Installazione

**Con i pulsanti (il modo più veloce)**
1. Premi [![Apri in HACS / Marketplace](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=domotica-lab&repository=risco-plus&category=integration)
   e conferma l'indirizzo del tuo Home Assistant: si apre Risco Plus nel Marketplace/HACS.
   Premi **Scarica** e riavvia Home Assistant.
2. Premi [![Aggiungi l'integrazione](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=risco_plus)
   per aggiungere l'integrazione.

La prima volta il sito *my.home-assistant.io* chiede l'indirizzo del tuo Home Assistant
(es. `http://homeassistant.local:8123`): lo ricorda per le volte successive.

**Con il Marketplace/HACS, senza pulsanti**
1. **Impostazioni → Marketplace** (o HACS) → ⋮ → **Repository personalizzati** → incolla
   `https://github.com/domotica-lab/risco-plus`, tipo **Integrazione** → Aggiungi.
2. Cerca **Risco Plus** → **Scarica**.
3. Riavvia Home Assistant.

**A mano:** copia la cartella `custom_components/risco_plus` in
`/config/custom_components/risco_plus` e riavvia.

**Poi:** Impostazioni → Dispositivi e servizi → **Aggiungi integrazione** → **Risco Plus**.
- Se usavi già l'integrazione **Risco**, scegli **"Copia dall'integrazione Risco di serie"**:
  account e opzioni vengono copiati, la vecchia integrazione viene **disattivata** (non
  cancellata) e le entità mantengono **gli stessi nomi** (es. `alarm_control_panel.allarme`),
  con nomi personalizzati e aree. Plance e automazioni continuano a funzionare.
  Quando hai controllato che tutto va, puoi eliminare la vecchia integrazione Risco.
- Altrimenti scegli **Risco Cloud** o **Centrale Risco locale** e inserisci i dati.

### Se usavi la vecchia versione di Risco Plus (cartella `custom_components/risco`)
1. Installa questa versione e aggiungi l'integrazione scegliendo **"Copia dall'integrazione
   Risco di serie"**: vengono copiate anche le opzioni di Risco Plus.
2. Cancella la cartella `/config/custom_components/risco`.
3. Cancella la vecchia risorsa della scheda (Impostazioni → Plance → ⋮ → Risorse, es.
   `/local/risco-casa-card.js`) e il file in `/config/www/`.
4. Riavvia Home Assistant. Le azioni diventano `risco_plus.arm_groups` e
   `risco_plus.set_time`: aggiorna le automazioni che le usano.

## Opzioni (Impostazioni → Dispositivi e servizi → Risco Plus → Configura)

- **Richiedi il codice per inserire / disinserire**: come nell'integrazione di serie.
- **Risco Plus**
  - **Codice per inserire/disinserire da Home Assistant**: se lo compili, vale solo questo
    (il PIN dell'utente Risco resta noto solo a Home Assistant) e viene **sempre chiesto
    per disinserire**, anche se "Richiedi il codice per disinserire" è spento.
    Per inserire serve solo se attivi "Richiedi il codice per inserire".
    Meglio usare solo cifre: così compare il tastierino numerico (con lettere compare la
    tastiera normale).
  - **Nomi dei gruppi**: una riga per gruppo, per esempio:
    ```
    A: Primo piano
    B: Balconi
    ```
  - **Crea un'entità per ogni gruppo**: per ogni partizione aggiunge 4 sensori
    ("Gruppo B inserito", acceso quando il gruppo è inserito) e 4 pulsanti
    ("Inserisci gruppo B"). Se spegni l'opzione, le entità vengono tolte.
  - **Con zone aperte all'inserimento**: cosa fare se c'è qualcosa aperto quando inserisci
    da Home Assistant (scheda, pannello allarme, automazioni, voce):
    - *Non controllare*: come l'integrazione di serie (predefinito).
    - *Non inserire e avvisa, se è aperta una zona dei gruppi da inserire*: **non serve
      scegliere nessuna zona**, vengono controllate tutte quelle dei gruppi che stai
      inserendo (con Totale tutte). Sulla scheda compare il messaggio con le zone aperte.
    - *Non inserire e avvisa, solo per le zone scelte sotto*: controlla solo le zone scelte.
    - *Escludi le zone aperte e inserisci*: come l'app iRISCO. Esclude le zone aperte dei
      gruppi e inserisce; le zone scelte sotto bloccano
      comunque. L'esclusione dura fino al disinserimento.
    Per avvisi sul telefono ci sono gli eventi `risco_arming_refused` e
    `risco_zones_bypassed` (dati: `entity_id`, `zones`), da usare nelle tue automazioni.
  - **Mostra anche una notifica in Home Assistant**: spenta di serie. Se la accendi, oltre al
    messaggio sulla scheda compare una notifica nel pannello di Home Assistant.
  - **Zone scelte**: servono solo alle ultime due scelte qui sopra.
- **Zone dei gruppi** (sezione a parte): con Risco Cloud la centrale di solito non comunica
  a quali gruppi appartiene una zona. Per ogni gruppo scegli le sue zone dall'elenco, così
  vengono controllate solo le zone dei gruppi che stai inserendo. Una zona non elencata vale
  per **tutti** i gruppi. Con il collegamento locale i gruppi li dà la centrale e non serve.
  Resta anche il vecchio campo di testo (`Finestra cucina: BC`, una riga per zona).
  - **Leggi lo stato dalla copia di Risco Cloud**: consigliato con moduli IP vecchi, oppure se
    l'app iRISCO dà errori mentre Home Assistant è acceso. Lo stato si aggiorna con
    l'intervallo impostato (predefinito 30 s); i comandi vanno sempre alla centrale.

Dopo la prima schermata ce ne sono due per le **modalità**:
1. **Stati Risco → stati di Home Assistant**: lo stato da mostrare per Totale, Parziale e
   ogni gruppo.
2. **Modalità di Home Assistant → Risco**: cosa inserisce ogni modalità (Fuori casa, In casa,
   Notte, Esclusione personalizzata). Oltre a Totale, Parziale e un gruppo si possono scegliere
   **più gruppi insieme**, per esempio *Attivo notte = Gruppi B + C*. Le modalità lasciate su
   "Non usato" non compaiono nel pannello allarme. Quando sono inseriti esattamente quei
   gruppi, l'allarme mostra quella modalità (es. "Attivo notte").

Come viene applicato il controllo:
- **Totale / inserimento parziale**: conta qualsiasi zona aperta.
- **Gruppi** (azione, pulsanti o modalità mappate su gruppi): contano solo le zone di quei gruppi.
- Attenzione ai **sensori di movimento** interni: se qualcuno passa davanti proprio mentre
  inserisci, la zona risulta aperta per qualche secondo.

## Azione `risco_plus.arm_groups`

```yaml
action: risco_plus.arm_groups
target:
  entity_id: alarm_control_panel.allarme
data:
  groups: ["B", "C"]
```
I gruppi vengono inseriti uno dopo l'altro (2 secondi di pausa). Il controllo delle zone
aperte, se attivo, avviene prima del primo comando.
Se è attivo "Richiedi il codice per inserire", aggiungi `code: "il tuo codice"` sotto `data`
(senza codice giusto non viene inserito niente).

## Scheda per la plancia

La scheda è inclusa nell'integrazione e si carica da sola (dopo aver aggiunto l'integrazione,
ricarica la pagina con Ctrl+F5). Se compare "Custom element doesn't exist: risco-plus-card",
aggiungila a mano: Impostazioni → Plance → ⋮ → Risorse → Aggiungi risorsa →
`/risco_plus/risco-plus-card.js`, tipo **Modulo JavaScript**. Aggiungila a una plancia (vedi
`esempi/scheda.yaml`):
```yaml
type: custom:risco-plus-card
entity: alarm_control_panel.allarme
```
Mostra i gruppi A-D con i loro nomi (tocca per selezionare, poi **Inserisci**), **Totale** solo
quando l'allarme è disinserito, **Disinserisci** con la finestra del codice originale di Home
Assistant. Testi in italiano o inglese secondo la lingua di Home Assistant. Il vecchio nome
`custom:risco-casa-card` funziona ancora.

## Eventi per le notifiche sul telefono

| Evento | Quando | Dati |
|---|---|---|
| `risco_arming_refused` | inserimento rifiutato per zone aperte | `entity_id`, `zones` |
| `risco_zones_bypassed` | zone escluse prima di inserire | `entity_id`, `zones` |

Esempio pronto: `esempi/automazione-zone-aperte.yaml`.

## Limiti noti

- Con **Risco Cloud** ogni comando apre una sessione con la centrale: per qualche minuto
  dopo un comando da Home Assistant, l'app iRISCO di un altro utente può essere rifiutata
  (e viceversa). Dipende dal cloud Risco e dai moduli IP più vecchi, non da Home Assistant.
- Con la centrale **inserita in parziale** Risco Cloud rifiuta il Totale: la scheda lo nasconde.
- Un account Risco = **un impianto**: per due centrali servono due account Risco.
- La centrale Risco **non disinserisce un gruppo alla volta**: "Disinserisci" toglie tutta la
  partizione.
- Con più **partizioni** ogni partizione ha la sua entità allarme (e le sue entità dei
  gruppi): serve una scheda per partizione.

## Test

I test sono quelli dell'integrazione di serie (adattati) più quelli delle funzioni nuove.
```bash
pip install pytest-homeassistant-custom-component "pyrisco>=0.8.1"
pytest
```
Provati con Home Assistant 2026.2.3 e Python 3.13 (ambiente di test disponibile): 63 test
superati. Su un Home Assistant 2026.10 reale la prova va fatta installando l'integrazione.

## Icona

L'icona (`custom_components/risco_plus/brand/`) è originale: uno scudo con i gruppi A-D.
Home Assistant (dalla 2026.3) la mostra da sola. Risco è un marchio di Risco Group: questa
integrazione non è prodotta né approvata da Risco Group.

## Licenza

Apache 2.0 (vedi `LICENSE`). Deriva dall'integrazione Risco di Home Assistant
(© Home Assistant e contributori), modificata.
