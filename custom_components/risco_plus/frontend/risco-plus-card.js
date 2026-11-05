/*
 * Risco Plus Card - scheda allarme Risco con gruppi A-D
 * Richiede l'integrazione Risco Plus (azione risco_plus.arm_groups, attributo armed_groups).
 * La carica l'integrazione stessa: non serve aggiungerla tra le risorse.
 * Testi in italiano o inglese secondo la lingua di Home Assistant.
 *
 * Esempio:
 *   type: custom:risco-plus-card        (anche custom:risco-casa-card)
 *   entity: alarm_control_panel.allarme
 *   name: Allarme                       (facoltativo)
 *   icon_navigation: "#sensori"         (facoltativo: tocco sullo scudo)
 *   labels:                             (facoltativo: nomi sotto le lettere;
 *     A: Primo piano                     se manca usa i "Nomi dei gruppi" delle opzioni)
 */

const GRUPPI = ["A", "B", "C", "D"];

const STATI = {
  disarmed: { colore: "var(--green-color, #4caf50)", icona: "mdi:shield-off", testo: "disarmed" },
  armed_away: { colore: "var(--red-color, #f44336)", icona: "mdi:shield-lock", testo: "armed_away" },
  armed_home: { colore: "var(--amber-color, #ffc107)", icona: "mdi:shield-half-full", testo: "armed" },
  armed_night: { colore: "var(--amber-color, #ffc107)", icona: "mdi:shield-half-full", testo: "armed" },
  armed_vacation: { colore: "var(--amber-color, #ffc107)", icona: "mdi:shield-half-full", testo: "armed" },
  armed_custom_bypass: { colore: "var(--amber-color, #ffc107)", icona: "mdi:shield-half-full", testo: "armed" },
  arming: { colore: "var(--orange-color, #ff9800)", icona: "mdi:shield", testo: "arming" },
  disarming: { colore: "var(--orange-color, #ff9800)", icona: "mdi:shield", testo: "disarming" },
  pending: { colore: "var(--orange-color, #ff9800)", icona: "mdi:shield-alert", testo: "pending" },
  triggered: { colore: "var(--red-color, #f44336)", icona: "mdi:bell-ring", testo: "triggered" },
};

// testi della scheda (it / en)
const TESTI = {
  it: {
    disarmed: "Disinserito", armed_away: "Inserito totale", armed: "Inserito",
    arming: "In attivazione", disarming: "In disattivazione", pending: "In attesa del codice",
    triggered: "ALLARME!", unavailable: "Non disponibile", partial: "parziale",
    name: "Allarme", arm: "Inserisci", arm_groups: "Inserisci {g}", full: "Totale",
    confirm: "Tocca per confermare", disarm: "Disinserisci", disarm_title: "Disattiva",
    code: "Codice", close: "Chiudi", sensors: "Sensori",
    arming_groups: "Inserimento {g}\u2026", arming_full: "Inserimento totale\u2026",
    disarming_now: "Disinserimento\u2026",
    no_change: "Nessuna variazione dalla centrale: controlla il codice o riprova",
    error: "Errore: {e}",
    no_plus: "Inserimento a gruppi non disponibile (integrazione Risco Plus non attiva). Funzionano Totale e Disinserisci.",
    need_entity: "Specifica 'entity' (alarm_control_panel)",
    description: "Allarme Risco con gruppi A-D, totale e codice",
  },
  en: {
    disarmed: "Disarmed", armed_away: "Armed away", armed: "Armed",
    arming: "Arming", disarming: "Disarming", pending: "Waiting for code",
    triggered: "ALARM!", unavailable: "Unavailable", partial: "partial",
    name: "Alarm", arm: "Arm", arm_groups: "Arm {g}", full: "Full",
    confirm: "Tap to confirm", disarm: "Disarm", disarm_title: "Disarm",
    code: "Code", close: "Close", sensors: "Sensors",
    arming_groups: "Arming {g}\u2026", arming_full: "Arming away\u2026",
    disarming_now: "Disarming\u2026",
    no_change: "No change from the panel: check the code or try again",
    error: "Error: {e}",
    no_plus: "Group arming not available (Risco Plus integration not active). Full and Disarm still work.",
    need_entity: "Set 'entity' (alarm_control_panel)",
    description: "Risco alarm with groups A-D, full arm and code",
  },
};

function lingua(hass) {
  const l = ((hass && ((hass.locale && hass.locale.language) || hass.language)) || navigator.language || "en").toLowerCase();
  return l.startsWith("it") ? "it" : "en";
}

class RiscoCasaCard extends HTMLElement {
  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error(TESTI[lingua(null)].need_entity);
    }
    this._config = { labels: {}, ...config };
    this._selezionati = new Set();
    this._tastierino = false;
    this._codice = "";
    this._attesa = null;
    this._messaggio = null;
    this._confermaTotale = false;
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.addEventListener("click", (ev) => this._click(ev));
    }
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass.states[this._config.entity];
    const chiave = st
      ? `${st.state}|${(st.attributes.armed_groups || st.attributes.gruppi_inseriti || []).join(",")}`
      : "assente";
    if (chiave !== this._ultimaChiave) {
      const primaVolta = this._ultimaChiave === undefined;
      this._ultimaChiave = chiave;
      if (!primaVolta && this._attesa && this._obiettivoRaggiunto()) {
        this._attesa = null;
        this._obiettivo = null;
        clearTimeout(this._timerAttesa);
      }
      // i gruppi ormai inseriti non sono piu' selezionabili
      for (const g of this._inseriti()) this._selezionati.delete(g);
      this._render();
    }
  }

  // testo tradotto, con {g} / {e} sostituiti
  _t(chiave, valori = {}) {
    const tabella = TESTI[lingua(this._hass)];
    let testo = tabella[chiave] !== undefined ? tabella[chiave] : TESTI.en[chiave] || chiave;
    for (const [k, v] of Object.entries(valori)) testo = testo.replace(`{${k}}`, v);
    return testo;
  }

  // gruppi inseriti: attributo armed_groups (vecchio nome: gruppi_inseriti)
  _gruppiAttr() {
    const g = this._attr("armed_groups");
    return Array.isArray(g) ? g : this._attr("gruppi_inseriti") || [];
  }

  getCardSize() {
    return 5;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  /* ---------- dati ---------- */

  _stato() {
    const st = this._hass && this._hass.states[this._config.entity];
    return st ? st.state : "unavailable";
  }

  _attr(nome) {
    const st = this._hass && this._hass.states[this._config.entity];
    return st ? st.attributes[nome] : undefined;
  }

  _inseriti() {
    if (this._stato() === "armed_away") return new Set(GRUPPI);
    return new Set(this._gruppiAttr());
  }

  // nome del gruppo: "labels" della scheda, altrimenti i nomi impostati
  // nelle opzioni dell'integrazione (attributo group_names)
  _nomeGruppo(g) {
    const nomi = this._attr("group_names") || {};
    const nome = this._config.labels[g] || nomi[g] || "";
    return String(nome).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  }

  // integrazione: "risco_plus" (separata) oppure "risco" (vecchia versione che
  // sostituiva l'integrazione di serie)
  _dominio() {
    const s = (this._hass && this._hass.services) || {};
    return s.risco_plus ? "risco_plus" : "risco";
  }

  _richiedeCodice() {
    return !!this._attr("code_format");
  }

  // codice per inserire: solo se attivo "Richiedi il codice per inserire"
  _richiedeCodiceInserimento() {
    return this._richiedeCodice() && !!this._attr("code_arm_required");
  }

  /* ---------- azioni ---------- */


  _servizio(dominio, servizio, dati) {
    return this._hass
      .callService(dominio, servizio, { entity_id: this._config.entity, ...dati })
      .catch((err) => {
        // comando rifiutato: niente attesa, si mostra subito il motivo
        this._attesa = null;
        this._obiettivo = null;
        clearTimeout(this._timerAttesa);
        // il messaggio arriva gia' tradotto da Home Assistant (es. zone aperte)
        const testo = (err && err.message) || String(err);
        this._mostra(testo, true, 10000);
      });
  }

  // l'attesa finisce solo quando la centrale ha completato TUTTO il comando
  _obiettivoRaggiunto() {
    const ob = this._obiettivo;
    if (!ob) return true;
    const stato = this._stato();
    if (ob.tipo === "totale") return stato === "armed_away";
    if (ob.tipo === "disinserisci") return stato === "disarmed";
    const inseriti = this._inseriti();
    return [...ob.gruppi].every((g) => inseriti.has(g));
  }

  _inAttesa(testo, obiettivo = null) {
    this._attesa = testo;
    this._obiettivo = obiettivo;
    clearTimeout(this._timerAttesa);
    this._timerAttesa = setTimeout(() => {
      if (this._attesa) {
        this._attesa = null;
        this._obiettivo = null;
        this._mostra(this._t("no_change"), true);
      }
    }, 30000);
    this._render();
  }

  _mostra(testo, errore = false, durata = 5000) {
    this._messaggio = { testo, errore };
    clearTimeout(this._timerMessaggio);
    this._timerMessaggio = setTimeout(() => {
      this._messaggio = null;
      this._render();
    }, durata);
    this._render();
  }

  _click(ev) {
    const el = ev.target.closest("[data-azione]");
    if (!el || el.disabled) return;
    const azione = el.dataset.azione;

    if (azione === "sensori") {
      const dest = this._config.icon_navigation;
      if (!dest) return;
      if (dest.startsWith("#")) {
        window.history.pushState(null, "", window.location.pathname + window.location.search + dest);
      } else {
        window.history.pushState(null, "", dest);
      }
      window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
      return;
    }

    if (azione === "gruppo") {
      const g = el.dataset.gruppo;
      if (this._inseriti().has(g)) return;
      this._selezionati.has(g) ? this._selezionati.delete(g) : this._selezionati.add(g);
      this._render();
    } else if (azione === "inserisci") {
      const gruppi = [...this._selezionati].sort();
      if (!gruppi.length) return;
      const inserisci = (codice) => {
        this._selezionati.clear();
        this._inAttesa(this._t("arming_groups", { g: gruppi.join("+") }), { tipo: "gruppi", gruppi: new Set(gruppi) });
        this._servizio(this._dominio(), "arm_groups", codice ? { groups: gruppi, code: codice } : { groups: gruppi });
      };
      if (this._richiedeCodiceInserimento()) this._chiediCodice("arm", inserisci);
      else inserisci();
    } else if (azione === "totale") {
      if (this._stato() !== "disarmed") return;
      if (!this._confermaTotale) {
        this._confermaTotale = true;
        clearTimeout(this._timerConferma);
        this._timerConferma = setTimeout(() => {
          this._confermaTotale = false;
          this._render();
        }, 4000);
        this._render();
        return;
      }
      this._confermaTotale = false;
      const totale = (codice) => {
        this._selezionati.clear();
        this._inAttesa(this._t("arming_full"), { tipo: "totale" });
        this._servizio("alarm_control_panel", "alarm_arm_away", codice ? { code: codice } : {});
      };
      if (this._richiedeCodiceInserimento()) this._chiediCodice("arm", totale);
      else totale();
    } else if (azione === "disinserisci") {
      if (this._richiedeCodice()) {
        this._chiediCodice("disarm", (codice) => {
          this._inAttesa(this._t("disarming_now"), { tipo: "disinserisci" });
          this._servizio("alarm_control_panel", "alarm_disarm", { code: codice });
        });
        return;
      }
      {
        this._inAttesa(this._t("disarming_now"), { tipo: "disinserisci" });
        this._servizio("alarm_control_panel", "alarm_disarm", {});
      }
    } else if (azione === "cifra") {
      if (this._codice.length < 10) this._codice += el.dataset.cifra;
      this._render();
    } else if (azione === "cancella") {
      this._codice = this._codice.slice(0, -1);
      this._render();
    } else if (azione === "svuota") {
      this._codice = "";
      this._render();
    } else if (azione === "occhio") {
      this._mostraCodice = !this._mostraCodice;
      this._render();
    } else if (azione === "annulla") {
      this._chiudiTastierino();
    } else if (azione === "ok") {
      if (!this._codice) return;
      const codice = this._codice;
      const azione = this._azioneCodice;
      this._chiudiTastierino(() => {
        if (azione) azione(codice);
      });
    }
  }

  // Usa la finestra del codice ORIGINALE di Home Assistant (la stessa del pannello
  // allarme di serie), messa a disposizione delle schede personalizzate.
  // Se per qualche motivo non e' disponibile, usa il tastierino della scheda.
  // tipo: "arm" (inserire) o "disarm" (disinserire); azione(codice) parte dopo l'OK
  async _chiediCodice(tipo, azione) {
    this._azioneCodice = azione;
    this._titoloCodice = tipo === "arm" ? this._t("arm") : this._t("disarm_title");
    let helpers = null;
    try {
      helpers = window.loadCardHelpers ? await window.loadCardHelpers() : null;
    } catch (e) {
      helpers = null;
    }
    if (!helpers || typeof helpers.showEnterCodeDialog !== "function") {
      this._apriTastierino();
      return;
    }
    const testo = tipo === "arm"
      ? this._titoloCodice
      : (this._hass.localize && this._hass.localize("ui.card.alarm_control_panel.disarm")) || this._titoloCodice;
    const codice = await helpers.showEnterCodeDialog(this, {
      codeFormat: this._attr("code_format") || "number",
      title: testo,
      submitText: testo,
    });
    if (codice == null || codice === "") return;
    azione(codice);
  }

  _apriTastierino() {
    this._tastierino = true;
    this._foglio = window.matchMedia("(max-width: 870px), (max-height: 500px)").matches;
    this._animazione = "entra";
    this._codice = "";
    this._render();
    this._animazione = null;
  }

  // chiusura con la stessa animazione delle finestre di Home Assistant
  _chiudiTastierino(dopo, daTrascinamento = false) {
    if (this._chiusura) return;
    const ridotto = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const durata = ridotto ? 0 : this._foglio ? 300 : 200;
    this._chiusura = true;
    if (daTrascinamento) {
      // il foglio continua a scendere dalla posizione in cui l'hai lasciato
      const f = this.shadowRoot.querySelector(".tastierino");
      const v = this.shadowRoot.querySelector(".velo");
      if (f) {
        f.style.transition = `transform ${durata}ms ease-out`;
        f.style.transform = "translateY(100%)";
      }
      if (v) {
        v.style.transition = `opacity ${durata}ms ease`;
        v.style.opacity = "0";
        v.style.pointerEvents = "none";
      }
    } else {
      this._animazione = "esce";
      this._render();
    }
    setTimeout(() => {
      this._chiusura = false;
      this._animazione = null;
      this._mostraCodice = false;
      this._tastierino = false;
      this._codice = "";
      if (dopo) dopo();
      this._render();
    }, durata);
  }

  // trascina in basso per chiudere (stessa logica di ha-bottom-sheet)
  _collegaTrascinamento() {
    const f = this.shadowRoot.querySelector(".tastierino.foglio");
    if (!f) return;
    let inizio = null, delta = 0, punti = [];
    f.addEventListener("touchstart", (ev) => {
      if (this._chiusura) return;
      inizio = ev.touches[0].clientY; delta = 0;
      punti = [{ y: inizio, t: performance.now() }];
      f.style.transition = "none";
    }, { passive: true });
    f.addEventListener("touchmove", (ev) => {
      if (inizio === null) return;
      const y = ev.touches[0].clientY;
      delta = Math.max(0, y - inizio);
      punti.push({ y, t: performance.now() });
      if (punti.length > 5) punti.shift();
      if (delta > 0) {
        ev.preventDefault();
        f.style.transform = `translateY(${delta}px)`;
      }
    }, { passive: false });
    const fine = () => {
      if (inizio === null) return;
      inizio = null;
      const a = punti[0], b = punti[punti.length - 1];
      const velocita = a && b && b.t > a.t ? (b.y - a.y) / (b.t - a.t) : 0;
      if (delta > 0 && (velocita > 0.5 || delta > f.offsetHeight * 0.5)) {
        this._chiudiTastierino(null, true);
      } else {
        f.style.transition = "transform 300ms ease-out";
        f.style.transform = "";
      }
    };
    f.addEventListener("touchend", fine);
    f.addEventListener("touchcancel", fine);
  }

  /* ---------- grafica ---------- */

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const stato = this._stato();
    const base = STATI[stato] || { colore: "#8a8f98", icona: "mdi:shield-remove", testo: "unavailable" };
    const info = { ...base, testo: this._t(base.testo) };
    const inseriti = this._inseriti();
    // controllo di sicurezza: la modifica all'integrazione e' attiva?
    const h = this._hass || {};
    const st0 = h.states ? h.states[this._config.entity] : null;
    const modAttiva = !h.states || !!(h.services && h.services[this._dominio()] && h.services[this._dominio()].arm_groups)
      && !!(st0 && st0.attributes && ("armed_groups" in st0.attributes || "gruppi_inseriti" in st0.attributes));
    const disponibile = !!STATI[stato];
    const gruppiOk = disponibile && modAttiva;
    const inserito = stato.startsWith("armed") || stato === "arming" || stato === "pending" || stato === "triggered";
    const totale = stato === "armed_away";

    let sottotitolo = info.testo;
    if (stato.startsWith("armed") && !totale) {
      sottotitolo = `${this._t("armed")} \u00b7 ${[...inseriti].sort().join(" + ") || this._t("partial")}`;
    }

    const occupato = !!this._attesa;
    const nSel = this._selezionati.size;

    // durante un comando mostra subito il risultato finale, senza i passaggi intermedi
    const ob = occupato ? this._obiettivo : null;
    let inArrivo = new Set();
    let coloreArrivo = "ambra";
    if (ob && ob.tipo === "gruppi") inArrivo = ob.gruppi;
    if (ob && ob.tipo === "totale") { inArrivo = new Set(GRUPPI); coloreArrivo = "rosso"; }
    if (occupato) sottotitolo = this._attesa;
    const coloreTesta = occupato ? "var(--orange-color, #ff9800)" : info.colore;

    const gruppiHtml = GRUPPI.map((g) => {
      const arriva = inArrivo.has(g) && !(ob && ob.tipo === "totale" && totale);
      const on = (inseriti.has(g) && !(ob && ob.tipo === "disinserisci")) || arriva;
      const sel = this._selezionati.has(g);
      const etichetta = this._nomeGruppo(g);
      const tot = (on && totale) || (arriva && coloreArrivo === "rosso");
      return `
        <button class="gruppo ${on ? "on" : ""} ${tot ? "tot" : ""} ${sel ? "sel" : ""} ${arriva ? "arriva" : ""}"
          data-azione="gruppo" data-gruppo="${g}" ${on || occupato || !gruppiOk ? "disabled" : ""}>
          <span class="lettera">${g}</span>
          ${etichetta ? `<span class="etichetta">${etichetta}</span>` : ""}
        </button>`;
    }).join("");

    const tastierinoHtml = this._tastierino
      ? `
      <div class="velo ${this._foglio ? "foglio" : ""} ${this._animazione || ""}" data-azione="annulla"></div>
      <div class="tastierino ${this._foglio ? "foglio" : ""} ${this._animazione || ""}" role="dialog">
        ${this._foglio ? `<div class="maniglia"></div>` : ""}
        <div class="pop-testa">
          <button class="chiudi" data-azione="annulla" title="${this._t("close")}"><ha-icon icon="mdi:close"></ha-icon></button>
          <div class="titolo-pop">${this._titoloCodice || this._t("disarm_title")}</div>
        </div>
        <div class="corpo">
          <div class="campo ${this._codice ? "pieno" : ""}">
            <span class="etichetta-campo">${this._t("code")}</span>
            <span class="valore">${this._mostraCodice ? this._codice : "\u25cf".repeat(this._codice.length)}</span>
            <button class="occhio" data-azione="occhio"><ha-icon icon="${this._mostraCodice ? "mdi:eye-off" : "mdi:eye"}"></ha-icon></button>
          </div>
          <div class="tasti">
            ${["1", "2", "3", "4", "5", "6", "7", "8", "9"]
              .map((c) => `<button class="tasto" data-azione="cifra" data-cifra="${c}">${c}</button>`)
              .join("")}
            <button class="tasto svuota" data-azione="svuota" ${this._codice ? "" : "disabled"}><ha-icon icon="mdi:close"></ha-icon></button>
            <button class="tasto" data-azione="cifra" data-cifra="0">0</button>
            <button class="tasto ok" data-azione="ok"><ha-icon icon="mdi:check"></ha-icon></button>
          </div>
        </div>
      </div>`
      : "";

    // la centrale non accetta il totale se e' gia' inserita in parziale:
    // il pulsante Totale compare solo quando l'allarme e' disinserito
    const puoTotale = !totale && !inserito && !(ob && ob.tipo === "gruppi");
    if (!puoTotale) this._confermaTotale = false;
    const azioniHtml = `
      <div class="azioni">
        ${!totale ? `
          <button class="azione verde ${nSel ? "attiva" : ""}" data-azione="inserisci" ${nSel && !occupato && gruppiOk ? "" : "disabled"}>
            <ha-icon icon="mdi:shield-plus"></ha-icon>
            <span>${nSel ? this._t("arm_groups", { g: [...this._selezionati].sort().join("+") }) : this._t("arm")}</span>
          </button>` : ""}
        ${puoTotale ? `
          <button class="azione rossa ${this._confermaTotale ? "conferma" : ""}" data-azione="totale" ${occupato || !disponibile ? "disabled" : ""}>
            <ha-icon icon="mdi:shield-lock"></ha-icon>
            <span>${this._confermaTotale ? this._t("confirm") : this._t("full")}</span>
          </button>` : ""}
        ${inserito ? `
          <button class="azione neutra" data-azione="disinserisci" ${occupato ? "disabled" : ""}>
            <ha-icon icon="mdi:shield-off"></ha-icon>
            <span>${this._t("disarm")}</span>
          </button>` : ""}
      </div>`;

    const rigaInfo = this._attesa
      ? ""
      : this._messaggio
        ? `<div class="info ${this._messaggio.errore ? "errore" : ""}">${this._messaggio.testo}</div>`
        : disponibile && !modAttiva
          ? `<div class="info errore">${this._t("no_plus")}</div>`
          : "";

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          --c: ${coloreTesta};
          --verde: var(--green-color, #4caf50);
          --ambra: var(--amber-color, #ffc107);
          --rosso: var(--red-color, #f44336);
          --neutro: var(--state-inactive-color, var(--secondary-text-color));
        }
        ha-card { padding: 12px; overflow: hidden; }
        /* intestazione */
        .testa { display: flex; align-items: center; gap: 12px; padding: 2px; }
        .scudo {
          width: 48px; height: 48px; border-radius: 50%; flex: 0 0 auto;
          display: flex; align-items: center; justify-content: center;
          background: color-mix(in srgb, var(--c) 20%, transparent);
          color: var(--c); --mdc-icon-size: 24px; transition: background .3s, color .3s;
        }
        .scudo.allarme { animation: lampeggia 0.8s infinite; }
        .scudo.attesa { animation: pulsa 1.4s ease-in-out infinite; }
        @keyframes lampeggia { 50% { background: var(--c); color: #fff; } }
        @keyframes pulsa { 50% { opacity: .4; } }
        .scudo.cliccabile { cursor: pointer; -webkit-tap-highlight-color: transparent; }
        .scudo { --mdc-icon-size: 28px !important; }
        .nome { font-size: 17px; font-weight: 600; line-height: 22px; color: var(--primary-text-color); }
        .sotto { font-size: 15px; font-weight: 500; line-height: 20px; color: var(--c); }
        /* gruppi */
        .gruppi { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-top: 12px; }
        .gruppo {
          appearance: none; border: none; margin: 0; cursor: pointer; font-family: inherit;
          border-radius: 12px; padding: 12px 2px; min-width: 0; box-sizing: border-box;
          background: color-mix(in srgb, var(--primary-text-color) 8%, transparent);
          color: var(--primary-text-color);
          display: flex; flex-direction: column; align-items: center; gap: 6px;
          transition: background .2s ease;
          -webkit-tap-highlight-color: transparent; outline: none;
        }
        .gruppo .lettera {
          width: 44px; height: 44px; border-radius: 50%;
          display: flex; align-items: center; justify-content: center;
          background: color-mix(in srgb, var(--primary-text-color) 10%, transparent);
          color: var(--primary-text-color);
          font-size: 20px; font-weight: 600; line-height: 1;
          transition: background .2s ease, color .2s ease;
        }
        .gruppi .gruppo.arriva .lettera { animation: pulsa 1.4s ease-in-out infinite; }
        .gruppo .etichetta {
          font-size: 11px; line-height: 14px; color: var(--secondary-text-color);
          max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        @media (hover: hover) {
          .gruppo:not(:disabled):not(.sel):not(.on):hover { background: color-mix(in srgb, var(--primary-text-color) 12%, transparent); }
        }
        .gruppi .gruppo.sel { background: color-mix(in srgb, var(--verde) 22%, transparent); }
        .gruppi .gruppo.sel .lettera { background: var(--verde); color: #fff; }
        .gruppi .gruppo.on { background: color-mix(in srgb, var(--ambra) 18%, transparent); cursor: default; opacity: 1; }
        .gruppi .gruppo.on .lettera { background: var(--ambra); color: #1c1c1c; }
        .gruppi .gruppo.on.tot { background: color-mix(in srgb, var(--rosso) 18%, transparent); }
        .gruppi .gruppo.on.tot .lettera { background: var(--rosso); color: #fff; }
        .gruppi .gruppo:disabled:not(.on) { opacity: .4; cursor: default; }
        /* pulsanti */
        .azioni { display: flex; gap: 8px; margin-top: 10px; }
        .azioni:empty { display: none; }
        .azione {
          flex: 1 1 0; min-width: 0; appearance: none; border: none; margin: 0;
          border-radius: 12px; height: 44px; padding: 0 10px;
          display: flex; align-items: center; justify-content: center; gap: 8px;
          font-family: inherit; font-size: 15px; font-weight: 600; cursor: pointer;
          --mdc-icon-size: 20px; transition: filter .2s ease, opacity .2s ease;
          -webkit-tap-highlight-color: transparent; outline: none;
        }
        .azione span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        @media (hover: hover) {
          .azione:not(:disabled):hover { filter: brightness(1.1); }
        }
        .azioni .azione:disabled { opacity: .45; cursor: default; }
        .azioni .verde { background: var(--ambra); color: #1c1c1c; }
        .azioni .rossa { background: var(--rosso); color: #fff; }
        .azioni .rossa.conferma { filter: brightness(1.2); box-shadow: 0 0 0 2px #fff inset; }
        .azioni .neutra { background: color-mix(in srgb, var(--primary-text-color) 12%, transparent); color: var(--primary-text-color); }
        .info {
          margin-top: 12px; font-size: .88em; color: var(--secondary-text-color);
          display: flex; align-items: center; gap: 8px;
        }
        .info.errore { color: #ff6b5e; }
        .spinner {
          width: 14px; height: 14px; border-radius: 50%;
          border: 2px solid var(--secondary-text-color); border-top-color: transparent;
          animation: gira .8s linear infinite;
        }
        @keyframes gira { to { transform: rotate(360deg); } }
        /* finestra codice, nello stile delle finestre di Home Assistant */
        .velo { position: fixed; inset: 0; background: var(--mdc-dialog-scrim-color, rgba(0,0,0,.32)); z-index: 998; }
        /* animazioni come ha-dialog: dissolvenza + leggero ingrandimento, 200 ms */
        .velo.entra { animation: velo-entra 200ms ease forwards; }
        .velo.esce { animation: velo-esce 200ms ease forwards; pointer-events: none; }
        .tastierino.entra { animation: pop-entra 200ms ease forwards; }
        .tastierino.esce { animation: pop-esce 200ms ease forwards; pointer-events: none; }
        @keyframes velo-entra { from { opacity: 0; } to { opacity: 1; } }
        @keyframes velo-esce { from { opacity: 1; } to { opacity: 0; } }
        @keyframes pop-entra { from { opacity: 0; scale: 0.8; } to { opacity: 1; scale: 1; } }
        @keyframes pop-esce { from { opacity: 1; scale: 1; } to { opacity: 0; scale: 0.8; } }
        /* telefono: foglio dal basso come ha-bottom-sheet, 300 ms */
        .velo.foglio.entra { animation-duration: 300ms; }
        .velo.foglio.esce { animation-duration: 300ms; }
        .tastierino.foglio.entra { animation: foglio-entra 300ms ease forwards; }
        .tastierino.foglio.esce { animation: foglio-esce 300ms ease forwards; pointer-events: none; }
        @keyframes foglio-entra { from { translate: 0 100%; } to { translate: 0 0; } }
        @keyframes foglio-esce { from { translate: 0 0; } to { translate: 0 100%; } }
        @media (prefers-reduced-motion: reduce) {
          .velo.entra, .velo.esce, .tastierino.entra, .tastierino.esce { animation-duration: 1ms !important; }
        }
        /* stesse misure di dialog-enter-code / ha-adaptive-dialog di Home Assistant */
        .tastierino {
          position: fixed; z-index: 999; inset: 0; margin: auto; height: fit-content; max-height: calc(100vh - 80px); overflow: auto;
          width: min(320px, 95vw); box-sizing: border-box; padding: 0;
          border-radius: var(--ha-dialog-border-radius, 24px);
          background: var(--ha-dialog-surface-background, var(--card-background-color, #1c1c1c));
          color: var(--primary-text-color);
          box-shadow: 0 11px 15px -7px rgba(0,0,0,.2), 0 24px 38px 3px rgba(0,0,0,.14), 0 9px 46px 8px rgba(0,0,0,.12);
          display: flex; flex-direction: column;
        }
        .tastierino.foglio {
          inset: auto 0 0 0; margin: 0; width: 100%; height: auto;
          max-height: min(90vh, calc(100vh - max(env(safe-area-inset-top), 48px)));
          max-height: min(90dvh, calc(100dvh - max(env(safe-area-inset-top), 48px)));
          border-radius: 20px 20px 0 0;
          background: var(--ha-bottom-sheet-surface-background, var(--ha-dialog-surface-background, var(--card-background-color, #1c1c1c)));
          box-shadow: none;
          padding: 0 env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
          touch-action: none;
        }
        .maniglia { position: absolute; top: 0; left: 0; width: 100%; padding-bottom: 2px; display: flex; justify-content: center; align-items: center; pointer-events: none; z-index: 1; }
        .maniglia::after { content: ""; margin: 6px 0; width: 40px; height: 4px; border-radius: 8px; background: var(--ha-bottom-sheet-handle-color, var(--divider-color, rgba(127,127,127,.4))); }
        /* intestazione (ha-dialog-header) */
        .pop-testa { display: flex; align-items: center; padding: 0 8px; box-sizing: border-box; height: 68px; flex: none; }
        .tastierino.foglio .pop-testa { padding: 0 4px; }
        .chiudi {
          width: 48px; height: 48px; flex: none; border: none; border-radius: 50%; background: none; cursor: pointer; padding: 0;
          color: var(--primary-text-color); display: flex; align-items: center; justify-content: center;
          --mdc-icon-size: 24px; -webkit-tap-highlight-color: transparent;
        }
        .titolo-pop {
          flex: 1; min-width: 0; padding: 0 4px; box-sizing: border-box;
          display: flex; align-items: center;
          font-size: 20px; line-height: 1.2; font-weight: 500; color: var(--primary-text-color);
          white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        }
        .corpo { padding: 0 24px 24px; display: flex; flex-direction: column; align-items: center; }
        /* campo codice (ha-input "material") */
        .campo {
          position: relative; width: 100%; height: 56px; box-sizing: border-box; padding: 0 4px 0 16px; margin-bottom: 8px;
          border-radius: 4px 4px 0 0;
          background: var(--ha-color-form-background, color-mix(in srgb, var(--primary-text-color) 10%, transparent));
          display: flex; align-items: center;
        }
        .campo::after {
          content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 1px;
          background: var(--ha-color-border-neutral-loud, color-mix(in srgb, var(--primary-text-color) 40%, transparent));
        }
        .etichetta-campo {
          position: absolute; left: 16px; top: 19px; font-size: 14px; line-height: 18px;
          color: var(--ha-color-text-secondary, var(--secondary-text-color)); transition: all .15s ease; pointer-events: none;
        }
        .campo.pieno .etichetta-campo { top: 10px; font-size: 12px; line-height: 14px; }
        .valore {
          flex: 1; padding-top: 14px; font-size: 16px; letter-spacing: 2px;
          color: var(--primary-text-color); overflow: hidden; white-space: nowrap;
        }
        .occhio {
          width: 40px; height: 40px; flex: none; border: none; border-radius: 50%; background: none; cursor: pointer; padding: 0;
          color: var(--ha-color-text-secondary, var(--secondary-text-color)); display: flex; align-items: center; justify-content: center;
          --mdc-icon-size: 24px; -webkit-tap-highlight-color: transparent;
        }
        /* tastierino (ha-control-button 56px) */
        .tasti {
          margin-top: 12px; padding: 12px;
          display: grid; grid-template-columns: repeat(3, auto); gap: 24px;
          justify-items: center; align-items: center; direction: ltr;
        }
        .tasto {
          --sfondo: var(--disabled-color, #6f6f6f);
          --opacita: 0.2;
          position: relative; overflow: hidden; z-index: 0;
          width: 56px; height: 56px; border: none; border-radius: 28px; padding: 8px; margin: 0;
          background: none; cursor: pointer;
          color: var(--primary-text-color); font-family: inherit; font-size: 24px; font-weight: 500; line-height: inherit;
          display: flex; align-items: center; justify-content: center; --mdc-icon-size: 24px;
          -webkit-tap-highlight-color: transparent; outline: none;
          transition: color 180ms ease-in-out;
        }
        .tasto::before {
          content: ""; position: absolute; inset: 0; z-index: -1;
          background-color: var(--sfondo); opacity: var(--opacita);
          transition: background-color 180ms ease-in-out, opacity 180ms ease-in-out;
        }
        .tasto:active::before { opacity: calc(var(--opacita) + 0.15); }
        .tasto.ok { --sfondo: var(--green-color, #4caf50); color: var(--green-color, #4caf50); }
        .tasto.svuota { --sfondo: var(--red-color, #f44336); color: var(--red-color, #f44336); }
        .tasto:disabled { --sfondo: var(--disabled-color, #6f6f6f); --opacita: 0.2; color: var(--disabled-text-color, #6f6f6f); cursor: not-allowed; }
        @media (hover: hover) {
          .chiudi:hover, .occhio:hover { background: rgba(127,127,127,.12); }
          .tasto:not(:disabled):hover::before { opacity: calc(var(--opacita) + 0.1); }
        }
        @media all and (max-height: 450px) {
          .tasti { grid-template-columns: repeat(6, auto); }
          .tasto.svuota { grid-row-start: 1; grid-column-start: 6; }
        }
      </style>
      <ha-card>
        <div class="testa">
          <div ${this._config.icon_navigation ? `data-azione="sensori" role="button" title="${this._t("sensors")}"` : ""} class="scudo ${this._config.icon_navigation ? "cliccabile" : ""} ${stato === "triggered" ? "allarme" : ""} ${occupato || ["arming", "disarming", "pending"].includes(stato) ? "attesa" : ""}"><ha-icon icon="${occupato ? "mdi:shield-sync" : info.icona}"></ha-icon></div>
          <div>
            <div class="nome">${this._config.name || this._t("name")}</div>
            <div class="sotto">${sottotitolo}</div>
          </div>
        </div>
        <div class="gruppi">${gruppiHtml}</div>
        ${azioniHtml}
        ${tastierinoHtml}
        ${rigaInfo}
      </ha-card>`;
    this._collegaTrascinamento();
  }
}

// nome nuovo e nome vecchio (per chi usa gia' custom:risco-casa-card)
if (!customElements.get("risco-plus-card")) {
  customElements.define("risco-plus-card", RiscoCasaCard);
}
if (!customElements.get("risco-casa-card")) {
  customElements.define("risco-casa-card", class extends RiscoCasaCard {});
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "risco-plus-card",
  name: "Risco Plus Card",
  description: TESTI[lingua(null)].description,
});
