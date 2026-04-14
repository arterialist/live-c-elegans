/**
 * C. elegans live viewer — WebSocket + canvas (pan/zoom, worm spine + parts).
 * Protocol v2: short JSON keys (see README).
 * Trajectory from `c`; hello `L` (layout);
 * each state may include `S` (V_m, 4 decimals), `F` (fired 0/1), and `R` (threshold r, 4 decimals).
 * Food UX: separate frames `fa` / `fr` / `fe` with `n` = count (viewer commands vs worm eaten).
 * Presence `t:"u"` with `n` = concurrent viewer count; client toasts join/leave from deltas.
 * Optional `bg.m4a` loops (lazy `src`, deferred play, `preload="none"`); `?nobg=1` / `?bg=0` skips.
 * Toast chimes reuse one `AudioContext` instead of constructing per beep.
 * Hello `M` = connectome metadata per neuron (parallel to `L.nm`).
 *
 * Rendering: CSS-pixel space + DPR bitmap; world→view via one canvas transform;
 * continuous requestAnimationFrame for FPS + TPS + sim s/s (TPS×dt) + smooth lerp between sim ticks.
 * Worm canvas: bottom-left scale bar ≈ physical 1 cm ↔ model mm.
 * Uses visualViewport.scale, devicePixelRatio, Firefox screen.mozMillimetersPerScreenPixel when present,
 * Windows screen.deviceXDPI when present; else CSS reference (96px/in). Calibrate: ruler-measure the bar’s
 * layout width in px for 1 real cm, then localStorage.setItem("celegans_physical_css_px_per_cm", value) or ?px_per_cm=.
 */
(function () {
  /**
   * Model seconds advanced per simulation tick (one MuJoCo mj_step per engine step).
   * Must match `active-inference/simulations/c_elegans/body_model.xml` `<option timestep="…">`.
   */
  const SIM_SECONDS_PER_TICK = 0.002;

  const params = new URLSearchParams(window.location.search);
  /** Optional: layout CSS px that equal one real centimeter with a ruler (overrides auto density). */
  const URL_PX_PER_CM = (() => {
    const raw = params.get("px_per_cm");
    if (raw == null || raw === "") return NaN;
    const v = parseFloat(raw);
    return v > 5 && v < 400 ? v : NaN;
  })();

  /** Model seconds per wall second from stream TPS (unrounded). */
  function formatSimSecondsPerWallSecond(tps) {
    const x = Number(tps) * SIM_SECONDS_PER_TICK;
    if (!Number.isFinite(x) || x < 0) return "—";
    return x.toFixed(4);
  }

  /** Layout CSS px per real-world centimeter; 0 = uncached. */
  let cssPxPerCmCache = 0;

  const LS_PX_PER_CM = "celegans_physical_css_px_per_cm";

  function invalidatePhysicalCmCache() {
    cssPxPerCmCache = 0;
  }

  function visualViewportScale() {
    const vv = window.visualViewport;
    if (vv && typeof vv.scale === "number" && vv.scale > 0.05 && vv.scale < 100) {
      return vv.scale;
    }
    return 1;
  }

  /**
   * Layout CSS pixels that span one physical centimeter on this display (best effort).
   * Combines devicePixelRatio, visualViewport pinch zoom, and OS-reported DPI when exposed.
   */
  function computeCssPixelsPerPhysicalCm() {
    const vvScale = visualViewportScale();
    const dpr = window.devicePixelRatio || 1;

    if (Number.isFinite(URL_PX_PER_CM)) {
      return URL_PX_PER_CM / vvScale;
    }
    try {
      const s = localStorage.getItem(LS_PX_PER_CM);
      if (s) {
        const v = parseFloat(s);
        if (v > 5 && v < 400) return v / vvScale;
      }
    } catch (_) {}

    const scr = window.screen;
    const mmpp = scr && scr.mozMillimetersPerScreenPixel;
    if (typeof mmpp === "number" && mmpp > 0.02 && mmpp < 3) {
      return 10 / mmpp / vvScale;
    }

    if (
      scr &&
      typeof scr.deviceXDPI === "number" &&
      scr.deviceXDPI >= 48 &&
      scr.deviceXDPI < 1200
    ) {
      return (2.54 * scr.deviceXDPI) / dpr / vvScale;
    }

    return (96 / 2.54) / vvScale;
  }

  function getCssPixelsPerCm() {
    if (cssPxPerCmCache > 0) return cssPxPerCmCache;
    cssPxPerCmCache = computeCssPixelsPerPhysicalCm();
    if (!(cssPxPerCmCache > 0)) cssPxPerCmCache = 96 / 2.54;
    return cssPxPerCmCache;
  }

  function formatMmPerScreenCm(mm) {
    if (!Number.isFinite(mm) || mm <= 0) return "—";
    if (mm >= 100) return mm.toFixed(1);
    if (mm >= 10) return mm.toFixed(2);
    if (mm >= 1) return mm.toFixed(2);
    return mm.toFixed(3);
  }

  /**
   * Map-style scale: horizontal bar ≈ physical 1 cm when it fits; label = model mm per that span.
   * If the panel is narrower than one physical cm in layout px, the bar is shortened; label still states mm / 1 cm.
   * Draw in worm panel CSS pixel space (current ctx transform should be dpr, origin top-left).
   */
  function drawScreenCmScale(ctx2d) {
    const cmPx = getCssPixelsPerCm();
    if (!cmPx || !wormCssW || !wormCssH) return;
    const mmPerScreenCm = cmPx / scale;
    const padL = 12;
    const padB = 10;
    const barH = 5;
    const tickUp = 7;
    const textAbove = 5;
    const barW = Math.min(cmPx, wormCssW - padL * 2);
    if (barW < 24) return;
    const x0 = padL;
    const yBarBot = wormCssH - padB;
    const yBarTop = yBarBot - barH;
    const yTickTop = yBarTop - tickUp;
    const fullCmBar = barW >= cmPx - 0.5;
    const label = fullCmBar
      ? "≈ " + formatMmPerScreenCm(mmPerScreenCm) + " mm model / 1 cm"
      : "≈ " +
          formatMmPerScreenCm(barW / scale) +
          " mm on bar · " +
          formatMmPerScreenCm(mmPerScreenCm) +
          " mm / 1 cm";

    ctx2d.save();
    ctx2d.strokeStyle = "#e8eaef";
    ctx2d.lineWidth = 1.25;
    ctx2d.beginPath();
    ctx2d.moveTo(x0, yBarBot);
    ctx2d.lineTo(x0, yTickTop);
    ctx2d.moveTo(x0 + barW, yBarBot);
    ctx2d.lineTo(x0 + barW, yTickTop);
    ctx2d.stroke();

    ctx2d.fillStyle = "rgba(232, 234, 239, 0.96)";
    ctx2d.fillRect(x0, yBarTop, barW, barH);
    ctx2d.strokeStyle = "#4a5568";
    ctx2d.lineWidth = 1;
    ctx2d.strokeRect(x0 + 0.5, yBarTop + 0.5, barW - 1, barH - 1);

    ctx2d.fillStyle = "#dfe4ee";
    ctx2d.shadowColor = "rgba(0,0,0,0.75)";
    ctx2d.shadowBlur = 4;
    ctx2d.shadowOffsetX = 0;
    ctx2d.shadowOffsetY = 1;
    ctx2d.font = "11px ui-monospace, Menlo, Consolas, monospace";
    ctx2d.textAlign = "left";
    ctx2d.textBaseline = "bottom";
    ctx2d.fillText(label, x0, yTickTop - textAbove);
    ctx2d.restore();
  }

  const DEFAULT_WS_URL = "wss://desired-lemming-square.ngrok-free.app";
  /** Upper cap for zoom (screen pixels per world mm); worm is sub-mm so allow deep zoom */
  const MAX_SCALE_PX_PER_MM = 800;
  const PROTOCOL = 2;
  /** Max COM samples kept client-side (was 2000 on server). */
  const TRAJECTORY_MAX = 2000;
  /** When trajectory has more points, draw every Nth sample (still capped by TRAJECTORY_MAX). */
  const TRAJECTORY_DRAW_CAP = 900;
  /** Initial guess for packet spacing before first measurement (ms). */
  const DEFAULT_TICK_MS = 1000 / 12;
  /** Max extrapolation past latest server pose, as a fraction of last blend span. */
  const EXTRAP_MAX_FRAC = 0.42;
  /** Hard cap on extrapolation (ms) so corrections stay small. */
  const EXTRAP_MAX_MS = 90;
  /** Touch: tap if press shorter than this (ms) and movement under slop. */
  const TOUCH_TAP_MAX_MS = 380;
  /** Touch: movement under this (CSS px) counts as tap / long-press anchor. */
  const TOUCH_TAP_MAX_DIST_PX = 14;
  /** Touch: hold still this long to remove food at press point. */
  const TOUCH_LONG_PRESS_MS = 520;
  /** Pinch: ignore smaller finger separation (CSS px) to avoid unstable zoom. */
  const PINCH_MIN_DIST_PX = 12;

  const WS_URL = params.get("ws") || DEFAULT_WS_URL;
  const NO_BG_MUSIC =
    params.get("nobg") === "1" || params.get("bg") === "0";

  const canvas = document.getElementById("c");
  const ctx =
    canvas.getContext("2d", { alpha: false, desynchronized: true }) ||
    canvas.getContext("2d");
  const neuralCanvas = document.getElementById("cn");
  const ctxN =
    neuralCanvas.getContext("2d", { alpha: false, desynchronized: true }) ||
    neuralCanvas.getContext("2d");
  const statusEl = document.getElementById("status");
  const onlineEl = document.getElementById("online");
  const tickHudEl = document.getElementById("tick-hud");
  const simTimeHudEl = document.getElementById("sim-time-hud");
  const fpsEl = document.getElementById("fps");
  const tpsEl = document.getElementById("tps");
  const simSpsEl = document.getElementById("sim-sps-hud");
  const barHintRow = document.getElementById("bar-hint-row");
  const controlsHint = document.getElementById("controls-hint");
  const hintDialog = document.getElementById("hint-dialog");
  const hintDialogHost = document.getElementById("hint-dialog-host");
  const hintOpenBtn = document.getElementById("bar-hint-open");
  const hintCloseBtn = document.getElementById("hint-dialog-close");

  /** Last `t:"u"` count; `-1` until first presence after connect (no join spam on first packet). */
  let lastPresenceN = -1;

  /** @type {object | null} latest server snapshot (authoritative tick / trail source) */
  let targetState = null;
  /** @type {object | null} snapshot at start of current blend (previous server frame) */
  let originState = null;
  /** performance.now() when targetState was last set from WebSocket */
  let blendStartMs = 0;
  /** Duration (ms) over which we interpolate origin → target; set from last inter-arrival gap. */
  let blendSpanMs = DEFAULT_TICK_MS;
  /** EMA of ms between state messages (fallback when gap unknown) */
  let tickMsEma = DEFAULT_TICK_MS;
  let lastMsgAtMs = 0;

  /** @type {number[][]} trajectory_mm from accumulated c (com_mm) */
  const trajectoryMm = [];
  let viewFitted = false;

  let cx = 0;
  let cy = 0;
  let scale = 8;
  let plateRadiusMm = 50;

  let panning = false;
  let panStartX = 0;
  let panStartY = 0;
  let panOrigCx = 0;
  let panOrigCy = 0;
  /** Which pointer is driving mouse-style pan (middle or shift+left). */
  let panPointerId = -1;

  /** Active pointers on worm canvas id → last client position. */
  const wormPtr = new Map();
  /** Previous pinch finger separation (CSS worm space) for incremental zoom. */
  let pinchPrevDist = 0;

  let touchDownId = -1;
  let touchDownClientX = 0;
  let touchDownClientY = 0;
  let touchDownAt = 0;
  let touchPanSlopPassed = false;
  let touchLongPressTimer = 0;
  let touchLongPressSent = false;

  /** Neural strip: pointer down for tap vs scroll discrimination. */
  let neuralDownClientX = 0;
  let neuralDownClientY = 0;
  let neuralDownAt = 0;

  /** Worm panel CSS size; updated in resize */
  let wormCssW = 800;
  let wormCssH = 600;
  /** Neural strip CSS size */
  let neuralCssW = 800;
  let neuralCssH = 200;
  let dpr = 1;

  /** @type {number[]|null} layout ax (Cook A→P) from hello L */
  let layoutAx = null;
  /** @type {number[]|null} */
  let layoutAy = null;
  /** @type {string[]|null} */
  let layoutNames = null;
  /** Hello `M`: Cook connectome row per PAULA id (parallel to `nm`). */
  let neuronMeta = null;
  /** @type {number[]} latest S (4-dec from server) */
  let lastNeuralS = [];
  /** @type {number[]} latest F 0/1 */
  let lastNeuralF = [];
  /** @type {number[]} latest dynamic firing threshold r (PAULA units), parallel to S */
  let lastNeuralR = [];

  let hoverNeuronIdx = -1;
  /** Last pointer over neural canvas (viewport px); tooltip anchor while mouse is still. */
  let neuralHoverClientX = 0;
  let neuralHoverClientY = 0;
  /** Layout from last drawNeural; used for hover hit-test (CSS px). */
  let lastNeuralLayout = null;
  const LS_ALERTS = "celegans_live_alerts_v1";
  let alertsWanted = false;
  try {
    alertsWanted = localStorage.getItem(LS_ALERTS) === "1";
  } catch (_) {}

  function alertsActive() {
    return (
      alertsWanted &&
      typeof Notification !== "undefined" &&
      Notification.permission === "granted"
    );
  }

  /** One Web Audio context for toast chimes (a new context per toast is costly). */
  let toastAudioCtx = null;

  const neuralTooltipEl = document.getElementById("neural-tooltip");
  const neuronModalEl = document.getElementById("neuron-modal");

  const MS_PER_DAY = 86400000;
  /** ~30 days: switch to date-first formatting (calendar scale). */
  const MS_PER_APPROX_MONTH = 30 * MS_PER_DAY;

  /**
   * tick × dt as ms since Unix epoch; formatted in a fixed offset (UTC) so all viewers see the same clock.
   * Under 1 day: time-of-day only. One day to ~30 days: date + time + ms.
   * From ~30 days: long calendar date + medium time (no fractional seconds).
   */
  function formatSimulationTime(tickNum) {
    const ms = tickNum * SIM_SECONDS_PER_TICK * 1000;
    if (!Number.isFinite(ms) || ms < 0) return "—";
    const d = new Date(ms);
    const tz = { timeZone: "UTC" };
    const h23 = { hourCycle: "h23" };

    if (ms < MS_PER_DAY) {
      try {
        return (
          new Intl.DateTimeFormat(undefined, {
            ...tz,
            ...h23,
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            fractionalSecondDigits: 3,
          }).format(d)
        );
      } catch (_) {
        const hh = String(d.getUTCHours()).padStart(2, "0");
        const mm = String(d.getUTCMinutes()).padStart(2, "0");
        const ss = String(d.getUTCSeconds()).padStart(2, "0");
        const fff = String(d.getUTCMilliseconds()).padStart(3, "0");
        return `${hh}:${mm}:${ss}.${fff}`;
      }
    }

    if (ms < MS_PER_APPROX_MONTH) {
      const opts = {
        ...tz,
        ...h23,
        weekday: "short",
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      };
      try {
        return (
          new Intl.DateTimeFormat(undefined, {
            ...opts,
            fractionalSecondDigits: 3,
          }).format(d)
        );
      } catch (_) {
        const base = new Intl.DateTimeFormat(undefined, opts).format(d);
        const frac = String(d.getUTCMilliseconds()).padStart(3, "0");
        return `${base}.${frac}`;
      }
    }

    try {
      return (
        new Intl.DateTimeFormat(undefined, {
          ...tz,
          dateStyle: "long",
          timeStyle: "medium",
        }).format(d)
      );
    } catch (_) {
      const y = d.getUTCFullYear();
      const mo = d.getUTCMonth() + 1;
      const da = d.getUTCDate();
      const hh = String(d.getUTCHours()).padStart(2, "0");
      const mm = String(d.getUTCMinutes()).padStart(2, "0");
      const ss = String(d.getUTCSeconds()).padStart(2, "0");
      return `${y}-${String(mo).padStart(2, "0")}-${String(da).padStart(2, "0")} ${hh}:${mm}:${ss}`;
    }
  }

  function setHudTickSimFromK(k) {
    if (!tickHudEl || !simTimeHudEl) return;
    const tickNum = Number(k);
    if (!Number.isFinite(tickNum) || tickNum < 0) {
      tickHudEl.textContent = "—";
      simTimeHudEl.textContent = "—";
      simTimeHudEl.removeAttribute("title");
      return;
    }
    tickHudEl.textContent = String(Math.trunc(tickNum));
    simTimeHudEl.textContent = formatSimulationTime(tickNum);
    const ms = tickNum * SIM_SECONDS_PER_TICK * 1000;
    simTimeHudEl.title =
      "Model time = tick × " +
      SIM_SECONDS_PER_TICK +
      " s from simulation epoch";
  }

  function reparentControlsHintToBar() {
    if (barHintRow && controlsHint && !barHintRow.contains(controlsHint)) {
      barHintRow.appendChild(controlsHint);
    }
  }

  function setupHintDialog() {
    if (
      !hintDialog ||
      !hintDialogHost ||
      !hintOpenBtn ||
      !hintCloseBtn ||
      !barHintRow ||
      !controlsHint
    ) {
      return;
    }
    hintOpenBtn.addEventListener("click", () => {
      if (hintDialog.open) return;
      hintDialogHost.appendChild(controlsHint);
      hintDialog.showModal();
      hintCloseBtn.focus();
    });
    hintCloseBtn.addEventListener("click", () => {
      hintDialog.close();
    });
    hintDialog.addEventListener("close", reparentControlsHintToBar);
    window.addEventListener("resize", () => {
      if (window.matchMedia("(min-width: 721px)").matches) {
        if (hintDialog.open) hintDialog.close();
        reparentControlsHintToBar();
      }
    });
  }

  setupHintDialog();

  const NEURON_KIND_LABEL = {
    s: "Sensory",
    m: "Motor",
    i: "Interneuron",
    u: "Unknown / other",
  };
  const COOK_2019_URL = "https://doi.org/10.1038/s41586-019-1352-7";
  const WORMBOOK_NEURO_URL =
    "https://www.wormbook.org/chapters/www_celegansVolII/neurobiology.html";
  const WORMWIRING_COOK_URL = "https://wormwiring.org/pages/emmonslab.html";

  /** WormBase SPA simple search (legacy `/search/site/` often shows no hits). */
  function wormBaseSimpleSearchUrl(name) {
    return (
      "https://www.wormbase.org/#/species/c_elegans/searches/simple?query=" +
      encodeURIComponent(name)
    );
  }

  /** Alliance aggregates WormBase + other sources; reliable hits for neuron names in expression. */
  function allianceCelegansSearchUrl(name) {
    return (
      "https://www.alliancegenome.org/search?q=" +
      encodeURIComponent(name) +
      "&species=" +
      encodeURIComponent("Caenorhabditis elegans")
    );
  }

  /** Space-separated terms use PubMed’s default AND; boolean `AND` in ?term= is flaky in some clients. */
  function pubmedNeuronLiteratureUrl(name) {
    const term = "c elegans " + name + " neuron";
    return "https://pubmed.ncbi.nlm.nih.gov/?term=" + encodeURIComponent(term);
  }

  function appendLinkItem(ul, href, label) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = label;
    li.appendChild(a);
    ul.appendChild(li);
  }

  function onNeuronModalKey(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeNeuronModal();
    }
  }

  function closeNeuronModal() {
    const modal = document.getElementById("neuron-modal");
    if (modal) modal.hidden = true;
    document.removeEventListener("keydown", onNeuronModalKey);
  }

  function openNeuronModal(idx) {
    const modal = document.getElementById("neuron-modal");
    const titleEl = document.getElementById("neuron-modal-title");
    const bodyEl = document.getElementById("neuron-modal-body");
    if (!modal || !titleEl || !bodyEl) return;
    const name = layoutNames && layoutNames[idx];
    if (!name) return;
    if (neuralTooltipEl) neuralTooltipEl.style.display = "none";

    titleEl.textContent = name;
    bodyEl.replaceChildren();

    const intro = document.createElement("p");
    intro.className = "neuron-modal-intro";
    intro.textContent =
      "Cook classification and synaptic degrees come from the connectome used to wire this simulation’s PAULA network. V_m and “fired” are live values from this run.";
    bodyEl.appendChild(intro);

    const dl = document.createElement("dl");
    function addRow(dt, ddText) {
      const dtt = document.createElement("dt");
      dtt.textContent = dt;
      const ddd = document.createElement("dd");
      ddd.textContent = ddText;
      dl.appendChild(dtt);
      dl.appendChild(ddd);
    }
    addRow("PAULA id", String(idx));
    const meta = neuronMeta && neuronMeta[idx];
    if (meta && typeof meta.k === "string") {
      addRow("Cook class", NEURON_KIND_LABEL[meta.k] || NEURON_KIND_LABEL.u);
      addRow(
        "Chemical synapses (in / out)",
        String(meta.ic) + " / " + String(meta.oc)
      );
      addRow("Gap junctions (in / out)", String(meta.ig) + " / " + String(meta.og));
    } else {
      addRow("Connectome metadata", "Not in hello (reconnect after server update).");
    }
    if (idx < lastNeuralS.length) {
      addRow("V_m (this tick)", String(lastNeuralS[idx]));
    }
    if (idx < lastNeuralR.length) {
      addRow("Threshold r (this tick)", String(lastNeuralR[idx]));
    }
    if (idx < lastNeuralF.length) {
      addRow("Fired (O>0)", lastNeuralF[idx] ? "Yes" : "No");
    }
    bodyEl.appendChild(dl);

    const h3 = document.createElement("h3");
    h3.textContent = "Read more (new tab)";
    bodyEl.appendChild(h3);
    const ul = document.createElement("ul");
    ul.className = "links";
    appendLinkItem(
      ul,
      COOK_2019_URL,
      "Cook et al. (2019), Nature — hermaphrodite connectome (this wiring’s source)"
    );
    appendLinkItem(
      ul,
      pubmedNeuronLiteratureUrl(name),
      "PubMed — keyword search: c elegans + " + name + " + neuron"
    );
    appendLinkItem(
      ul,
      allianceCelegansSearchUrl(name),
      "Alliance Genome — C. elegans search (genes / expression mentioning " +
        name +
        ")"
    );
    appendLinkItem(
      ul,
      wormBaseSimpleSearchUrl(name),
      "WormBase — simple search (same data; opens in SPA)"
    );
    appendLinkItem(
      ul,
      WORMBOOK_NEURO_URL,
      "WormBook — C. elegans neurobiology overview"
    );
    appendLinkItem(
      ul,
      WORMWIRING_COOK_URL,
      "WormWiring — Emmons lab / Cook et al. data portal"
    );
    bodyEl.appendChild(ul);

    modal.hidden = false;
    document.removeEventListener("keydown", onNeuronModalKey);
    document.addEventListener("keydown", onNeuronModalKey);
    const closeBtn = modal.querySelector(".neuron-modal-close");
    if (closeBtn instanceof HTMLElement) closeBtn.focus();
  }

  let fpsAccFrames = 0;
  let fpsAccStart = 0;
  /** Sum of Δtick since last HUD refresh (same window as FPS). */
  let tpsAccTicks = 0;
  /** Last state message `k` for TPS; `-1` until first packet after connect. */
  let tpsPrevK = -1;

  function smoothstep01(t) {
    const u = Math.min(1, Math.max(0, t));
    return u * u * (3 - 2 * u);
  }

  function cloneVisualState(s) {
    return {
      tick: s.tick,
      plate_radius_mm: s.plate_radius_mm,
      worm_radius_mm: s.worm_radius_mm,
      segments_mm: s.segments_mm.map((p) => [p[0], p[1]]),
      food_mm: (s.food_mm || []).map((p) => [p[0], p[1]]),
    };
  }

  function lerp(a, b, u) {
    return a + (b - a) * u;
  }

  /** @param {number} now performance.now() */
  function getRenderState(now) {
    if (!targetState || !targetState.segments_mm) return null;
    if (!originState || originState.tick === targetState.tick) return targetState;

    const span = Math.max(12, blendSpanMs);
    const elapsed = now - blendStartMs;
    const rawU = elapsed / span;
    /** Smooth in [0,1]; past one tick we extrapolate along last motion vector. */
    const u = rawU <= 1 ? smoothstep01(rawU) : 1;
    let extrapNorm = 0;
    if (rawU > 1) {
      const overMs = elapsed - span;
      const maxNorm = Math.min(EXTRAP_MAX_FRAC, EXTRAP_MAX_MS / span);
      extrapNorm = Math.min(overMs / span, maxNorm);
    }

    const o = originState;
    const t = targetState;
    const nSeg = Math.max(o.segments_mm.length, t.segments_mm.length);
    const segments_mm = [];
    for (let i = 0; i < nSeg; i++) {
      const os = o.segments_mm[i];
      const ts = t.segments_mm[i];
      if (os && ts) {
        const dx = ts[0] - os[0];
        const dy = ts[1] - os[1];
        const bx = lerp(os[0], ts[0], u) + dx * extrapNorm;
        const by = lerp(os[1], ts[1], u) + dy * extrapNorm;
        segments_mm.push([bx, by]);
      } else {
        segments_mm.push(ts ? [ts[0], ts[1]] : os ? [os[0], os[1]] : [0, 0]);
      }
    }
    const of = o.food_mm || [];
    const tf = t.food_mm || [];
    let food_mm = tf;
    if (of.length === tf.length && tf.length > 0) {
      food_mm = [];
      for (let i = 0; i < tf.length; i++) {
        const fx0 = of[i][0];
        const fy0 = of[i][1];
        const fx1 = tf[i][0];
        const fy1 = tf[i][1];
        const fdx = fx1 - fx0;
        const fdy = fy1 - fy0;
        food_mm.push([
          lerp(fx0, fx1, u) + fdx * extrapNorm,
          lerp(fy0, fy1, u) + fdy * extrapNorm,
        ]);
      }
    }
    return {
      tick: t.tick,
      plate_radius_mm: lerp(o.plate_radius_mm, t.plate_radius_mm, u),
      worm_radius_mm: lerp(o.worm_radius_mm, t.worm_radius_mm, u),
      segments_mm,
      food_mm,
    };
  }

  function resize() {
    const wrap = document.getElementById("canvas-wrap");
    const np = document.getElementById("neural-panel");
    dpr = window.devicePixelRatio || 1;
    wormCssW = wrap.clientWidth;
    wormCssH = wrap.clientHeight;
    canvas.width = Math.floor(wormCssW * dpr);
    canvas.height = Math.floor(wormCssH * dpr);
    canvas.style.width = wormCssW + "px";
    canvas.style.height = wormCssH + "px";

    neuralCssW = np ? np.clientWidth : 800;
    neuralCssH = np ? np.clientHeight : 200;
    neuralCanvas.width = Math.floor(neuralCssW * dpr);
    neuralCanvas.height = Math.floor(neuralCssH * dpr);
    neuralCanvas.style.width = neuralCssW + "px";
    neuralCanvas.style.height = neuralCssH + "px";
    invalidatePhysicalCmCache();
  }

  function screenToWorld(sx, sy) {
    const wx = cx + (sx - wormCssW / 2) / scale;
    const wy = cy - (sy - wormCssH / 2) / scale;
    return [wx, wy];
  }

  /** Viewport client coords → worm panel CSS pixel coords. */
  function clientToWormCss(clientX, clientY) {
    const rect = canvas.getBoundingClientRect();
    const sx = ((clientX - rect.left) / rect.width) * wormCssW;
    const sy = ((clientY - rect.top) / rect.height) * wormCssH;
    return [sx, sy];
  }

  function sendFoodAddWorld(wx, wy) {
    if (!window._ws || window._ws.readyState !== WebSocket.OPEN) return;
    window._ws.send(JSON.stringify({ p: PROTOCOL, t: "a", x: wx, y: wy }));
  }

  function sendFoodRemoveWorld(wx, wy) {
    if (!window._ws || window._ws.readyState !== WebSocket.OPEN) return;
    window._ws.send(JSON.stringify({ p: PROTOCOL, t: "v", x: wx, y: wy }));
  }

  /** Zoom about (sx,sy) in worm CSS space; factor < 1 zooms out. */
  function applyZoomAtCss(sx, sy, factor) {
    const [wmx, wmy] = screenToWorld(sx, sy);
    const newScale = Math.min(
      MAX_SCALE_PX_PER_MM,
      Math.max(0.25, scale * factor)
    );
    scale = newScale;
    cx = wmx - (sx - wormCssW / 2) / scale;
    cy = wmy + (sy - wormCssH / 2) / scale;
  }

  function wormPinchMetrics() {
    if (wormPtr.size !== 2) return null;
    const pts = Array.from(wormPtr.values());
    const a = pts[0];
    const b = pts[1];
    const [sx0, sy0] = clientToWormCss(a.clientX, a.clientY);
    const [sx1, sy1] = clientToWormCss(b.clientX, b.clientY);
    const dist = Math.hypot(sx1 - sx0, sy1 - sy0);
    const midSx = (sx0 + sx1) / 2;
    const midSy = (sy0 + sy1) / 2;
    return { dist, midSx, midSy };
  }

  function clearTouchLongPress() {
    if (touchLongPressTimer) {
      clearTimeout(touchLongPressTimer);
      touchLongPressTimer = 0;
    }
  }

  function resetTouchOneFinger() {
    clearTouchLongPress();
    touchDownId = -1;
    touchPanSlopPassed = false;
    touchLongPressSent = false;
  }

  /** Line width in world units for ~`px` screen pixels under current `scale`. */
  function lineWidthWorld(px) {
    return px / scale;
  }

  function trajectoryDrawStep(len) {
    if (len <= TRAJECTORY_DRAW_CAP) return 1;
    return Math.ceil(len / TRAJECTORY_DRAW_CAP);
  }

  /** @param {number} now performance.now() */
  function draw(now) {
    if (!fpsAccStart) fpsAccStart = now;
    fpsAccFrames++;
    if (now - fpsAccStart >= 500) {
      const elapsed = now - fpsAccStart;
      const fps = (fpsAccFrames * 1000) / elapsed;
      fpsEl.textContent = String(Math.round(fps));
      if (tpsEl) {
        if (tpsPrevK < 0 || elapsed <= 0) {
          tpsEl.textContent = "—";
          if (simSpsEl) simSpsEl.textContent = "—";
        } else {
          const tps = (tpsAccTicks * 1000) / elapsed;
          tpsEl.textContent = String(Math.round(tps));
          if (simSpsEl) simSpsEl.textContent = formatSimSecondsPerWallSecond(tps);
        }
        tpsAccTicks = 0;
      }
      fpsAccFrames = 0;
      fpsAccStart = now;
    }

    const lastState = getRenderState(now);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#1a1d24";
    ctx.fillRect(0, 0, wormCssW, wormCssH);

    if (!lastState || !lastState.segments_mm) {
      ctx.fillStyle = "#888";
      ctx.font = "14px system-ui";
      ctx.fillText("Waiting for simulation…", 16, 28);
      drawScreenCmScale(ctx);
      return;
    }

    const pr = lastState.plate_radius_mm ?? plateRadiusMm;
    plateRadiusMm = pr;
    const wormR = lastState.worm_radius_mm ?? 0.04;
    const segs = lastState.segments_mm;

    ctx.save();
    ctx.translate(wormCssW / 2, wormCssH / 2);
    ctx.scale(scale, -scale);
    ctx.translate(-cx, -cy);

    const lwPlate = lineWidthWorld(2);
    ctx.strokeStyle = "#3d4555";
    ctx.lineWidth = lwPlate;
    ctx.beginPath();
    ctx.arc(0, 0, pr, 0, Math.PI * 2);
    ctx.stroke();

    const tlen = trajectoryMm.length;
    if (tlen > 1) {
      const step = trajectoryDrawStep(tlen);
      ctx.strokeStyle = "rgba(100,140,200,0.25)";
      ctx.lineWidth = lineWidthWorld(1);
      ctx.beginPath();
      ctx.moveTo(trajectoryMm[0][0], trajectoryMm[0][1]);
      for (let i = step; i < tlen; i += step) {
        ctx.lineTo(trajectoryMm[i][0], trajectoryMm[i][1]);
      }
      if ((tlen - 1) % step !== 0) {
        ctx.lineTo(trajectoryMm[tlen - 1][0], trajectoryMm[tlen - 1][1]);
      }
      ctx.stroke();
    }

    // No thick polyline along the spine: at high lineWidth it self-overlaps when the worm
    // curls (head near tail) and reads as an unwanted filled band between endpoints.

    const diskRWorld = Math.max(lineWidthWorld(1.2), wormR * 0.92);
    const bodyFill = "rgba(230, 217, 153, 0.92)";
    const bodyStroke = "rgba(120, 100, 70, 0.5)";
    // Each segment is its own subpath: without moveTo before every arc(), Canvas adds
    // straight connectors between circles and fill() encloses a bogus polygon.
    ctx.beginPath();
    for (let i = 1; i < segs.length; i++) {
      const x = segs[i][0];
      const y = segs[i][1];
      ctx.moveTo(x + diskRWorld, y);
      ctx.arc(x, y, diskRWorld, 0, Math.PI * 2);
    }
    ctx.fillStyle = bodyFill;
    ctx.fill();
    ctx.strokeStyle = bodyStroke;
    ctx.lineWidth = lineWidthWorld(1);
    ctx.stroke();

    const headR = diskRWorld * 1.05;
    const hx = segs[0][0];
    const hy = segs[0][1];
    ctx.beginPath();
    ctx.moveTo(hx + headR, hy);
    ctx.arc(hx, hy, headR, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(166, 128, 89, 0.98)";
    ctx.fill();
    ctx.strokeStyle = "rgba(60, 45, 30, 0.6)";
    ctx.lineWidth = lineWidthWorld(1.2);
    ctx.stroke();

    const foods = lastState.food_mm || [];
    const nFood = foods.length;
    if (nFood > 0) {
      const foodRWorld = lineWidthWorld(9);
      ctx.beginPath();
      for (let i = 0; i < nFood; i++) {
        const f = foods[i];
        const fx = f[0];
        const fy = f[1];
        ctx.moveTo(fx + foodRWorld, fy);
        ctx.arc(fx, fy, foodRWorld, 0, Math.PI * 2);
      }
      ctx.fillStyle = "#c4b";
      ctx.fill();
      ctx.strokeStyle = "#202";
      ctx.lineWidth = lineWidthWorld(0.5);
      ctx.stroke();
    }

    ctx.restore();
    drawScreenCmScale(ctx);
  }

  /** Matches `connectome_layout._dv_offset` range for normalized y mapping. */
  const NEURAL_AY_LO = -0.62;
  const NEURAL_AY_HI = 0.62;

  function heatColor(t) {
    const u = Math.min(1, Math.max(0, t));
    const r = Math.floor(lerp(35, 255, u));
    const g = Math.floor(lerp(70, 230, u * u));
    const b = Math.floor(lerp(190, 45, u));
    return "rgb(" + r + "," + g + "," + b + ")";
  }

  function syncAlertsToggleLabel() {
    const btn = document.getElementById("alerts-toggle");
    if (!btn) return;
    const perm =
      typeof Notification !== "undefined" ? Notification.permission : "denied";
    if (alertsActive()) {
      btn.textContent = "Alerts: on";
      btn.classList.add("on");
      btn.title =
        "Toasts also go to system notifications + chime for food and viewer join/leave";
    } else if (alertsWanted && perm === "default") {
      btn.textContent = "Alerts: pending";
      btn.classList.remove("on");
      btn.title = "Click again and allow notifications in the browser prompt";
    } else {
      btn.textContent = "Alerts: off";
      btn.classList.remove("on");
      btn.title =
        "Enable browser notifications + sound for food and viewer join/leave (requires permission)";
    }
  }

  /** Short chime when desktop alerts are active (Notification uses silent:true to avoid double ding). */
  function playToastSound(opts) {
    if (!alertsActive()) return;
    opts = opts || {};
    const freq = opts.freq != null ? opts.freq : 560;
    const dur = opts.dur != null ? opts.dur : 0.075;
    const gain = opts.gain != null ? opts.gain : 0.065;
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      if (!toastAudioCtx) toastAudioCtx = new Ctx();
      const ctx = toastAudioCtx;
      void ctx.resume().catch(function () {});
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = "sine";
      o.frequency.value = freq;
      g.gain.value = gain;
      o.connect(g);
      g.connect(ctx.destination);
      o.start();
      o.stop(ctx.currentTime + dur);
    } catch (_) {}
  }

  function notifyDesktop(title, body) {
    if (!alertsActive()) return;
    try {
      new Notification(title, {
        body: body || title,
        silent: true,
      });
    } catch (_) {}
  }

  /**
   * @param {string} message
   * @param {{ title?: string, os?: boolean }} [opts]
   */
  /** Update bar label and show join/leave toasts when `n` changes (skips first packet after connect). */
  function applyPresenceCount(n) {
    if (onlineEl) {
      onlineEl.textContent = (n === 1 ? "1 viewer" : n + " viewers") + " online";
    }
    if (lastPresenceN < 0) {
      lastPresenceN = n;
      return;
    }
    if (n > lastPresenceN) {
      const d = n - lastPresenceN;
      showToast(d === 1 ? "A viewer joined" : d + " viewers joined", {
        title: "Viewers",
      });
    } else if (n < lastPresenceN) {
      const d = lastPresenceN - n;
      showToast(d === 1 ? "A viewer left" : d + " viewers left", {
        title: "Viewers",
      });
    }
    lastPresenceN = n;
  }

  /** Server food events (`fa` add / `fr` viewer remove / `fe` worm eaten), separate from `t:"s"`. */
  function showFoodEventToasts(msg) {
    const n = Number(msg.n);
    if (!Number.isFinite(n) || n < 1) return;
    if (msg.t === "fr") {
      showToast(n === 1 ? "Pellet removed" : n + " pellets removed", { title: "Food" });
    } else if (msg.t === "fe") {
      showToast(n === 1 ? "Food eaten!" : n + " pellets eaten!", { title: "Food" });
    } else if (msg.t === "fa") {
      showToast(n === 1 ? "Pellet placed" : n + " pellets placed", { title: "Food" });
    }
  }

  function showToast(message, opts) {
    opts = opts || {};
    const title = opts.title != null ? opts.title : "C. elegans live";
    const stack = document.getElementById("toast-stack");
    if (!stack) return;
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = message;
    stack.appendChild(el);
    window.setTimeout(() => {
      el.style.opacity = "0";
      el.style.transition = "opacity 0.28s ease";
      window.setTimeout(() => el.remove(), 300);
    }, 3400);
    while (stack.children.length > 5) {
      stack.removeChild(stack.firstChild);
    }
    if (opts.os !== false) {
      playToastSound();
      notifyDesktop(title, message);
    }
  }

  function pickNeuronAtCss(mx, my) {
    const L = lastNeuralLayout;
    if (!L || !layoutAx || !layoutAy) return -1;
    const thresh = (L.rad + 6) * (L.rad + 6);
    let best = -1;
    let bestD2 = 1e18;
    for (let i = 0; i < L.n; i++) {
      const x = L.marginLR + layoutAx[i] * L.pw;
      const y = L.marginTop + ((NEURAL_AY_HI - layoutAy[i]) / L.aySpan) * L.ph;
      const dx = mx - x;
      const dy = my - y;
      const d2 = dx * dx + dy * dy;
      if (d2 < bestD2) {
        bestD2 = d2;
        best = i;
      }
    }
    if (best < 0 || bestD2 > thresh) return -1;
    return best;
  }

  /** Tooltip + hover ring only when the UA reports real hover (not touch-primary). */
  function neuralFineHoverCapable() {
    try {
      return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
    } catch (_) {
      return true;
    }
  }

  function neuronModalIsOpen() {
    return Boolean(neuronModalEl && !neuronModalEl.hidden);
  }

  /** Refresh tooltip text/position from latest S/F (call from rAF and mousemove). */
  function syncNeuralTooltipFromHover() {
    if (!neuralTooltipEl || neuronModalIsOpen()) return;
    if (!neuralFineHoverCapable()) {
      neuralTooltipEl.style.display = "none";
      return;
    }
    const idx = hoverNeuronIdx;
    if (idx < 0 || !layoutNames || !layoutNames[idx]) {
      neuralTooltipEl.style.display = "none";
      return;
    }
    let line = layoutNames[idx];
    if (idx < lastNeuralS.length) {
      line += " · V_m=" + lastNeuralS[idx];
    }
    if (idx < lastNeuralR.length) {
      line += " · r=" + lastNeuralR[idx];
    }
    if (idx < lastNeuralF.length && lastNeuralF[idx]) {
      line += " · fired";
    }
    neuralTooltipEl.textContent = line;
    neuralTooltipEl.style.display = "block";

    const pad = 8;
    const gap = 12;
    let left = neuralHoverClientX + gap;
    let top = neuralHoverClientY + gap;
    neuralTooltipEl.style.left = left + "px";
    neuralTooltipEl.style.top = top + "px";

    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const r = neuralTooltipEl.getBoundingClientRect();

    if (r.right > vw - pad) {
      left = neuralHoverClientX - r.width - gap;
    }
    if (r.bottom > vh - pad) {
      top = neuralHoverClientY - r.height - gap;
    }

    left = Math.max(pad, Math.min(left, vw - r.width - pad));
    top = Math.max(pad, Math.min(top, vh - r.height - pad));

    neuralTooltipEl.style.left = left + "px";
    neuralTooltipEl.style.top = top + "px";
  }

  function drawNeural() {
    ctxN.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctxN.fillStyle = "#151820";
    ctxN.fillRect(0, 0, neuralCssW, neuralCssH);
    lastNeuralLayout = null;

    if (!layoutAx || !layoutAy || layoutAx.length !== layoutAy.length) {
      ctxN.fillStyle = "#777";
      ctxN.font = "12px system-ui";
      ctxN.fillText("Waiting for connectome layout (hello L)…", 10, 22);
      return;
    }

    const marginLR = 8;
    const marginTop = 8;
    const legendBand = 30;
    const pw = Math.max(1, neuralCssW - 2 * marginLR);
    const ph = Math.max(1, neuralCssH - marginTop - legendBand);
    const n = layoutAx.length;
    const rad = Math.max(1.1, Math.min(3.8, (pw / Math.max(80, n)) * 10));
    const aySpan = NEURAL_AY_HI - NEURAL_AY_LO;

    lastNeuralLayout = {
      marginLR,
      marginTop,
      legendBand,
      pw,
      ph,
      n,
      rad,
      aySpan,
    };

    const ns = lastNeuralS.length;
    const nr = lastNeuralR.length;
    const usePerNeuronR = nr === ns && ns > 0;

    let smin = Infinity;
    let smax = -Infinity;
    for (let i = 0; i < ns; i++) {
      const v = lastNeuralS[i];
      if (v < smin) smin = v;
      if (v > smax) smax = v;
    }
    if (!(smax > smin)) {
      smin = 0;
      smax = 1;
    }

    for (let i = 0; i < n; i++) {
      const x = marginLR + layoutAx[i] * pw;
      const y = marginTop + ((NEURAL_AY_HI - layoutAy[i]) / aySpan) * ph;
      let t = 0.5;
      if (i < ns) {
        if (usePerNeuronR) {
          const ri = lastNeuralR[i];
          const denom = Math.max(ri, 1e-6);
          t = Math.max(0, Math.min(1, lastNeuralS[i] / denom));
        } else {
          t = (lastNeuralS[i] - smin) / (smax - smin);
        }
      }
      ctxN.beginPath();
      ctxN.arc(x, y, rad, 0, Math.PI * 2);
      ctxN.fillStyle = heatColor(t);
      ctxN.fill();
      if (i < lastNeuralF.length && lastNeuralF[i]) {
        ctxN.strokeStyle = "rgba(255,255,255,0.92)";
        ctxN.lineWidth = 2;
        ctxN.stroke();
      }
      if (neuralFineHoverCapable() && i === hoverNeuronIdx) {
        ctxN.strokeStyle = "rgba(255, 210, 120, 0.95)";
        ctxN.lineWidth = 2.5;
        ctxN.beginPath();
        ctxN.arc(x, y, rad + 2.2, 0, Math.PI * 2);
        ctxN.stroke();
      }
    }

    ctxN.fillStyle = "#7a8a9a";
    ctxN.font = "11px system-ui";
    const legendY = neuralCssH - 8;
    ctxN.fillText(
      usePerNeuronR
        ? "Cook A→P (x) · D↑ V↓ (y) · fill=V_m / r · ring=fired"
        : "Cook A→P (x) · D↑ V↓ (y) · fill=V_m (global) · ring=fired",
      marginLR,
      legendY
    );
  }

  function applyStateMsg(msg) {
    const now = performance.now();
    const incoming = {
      tick: msg.k,
      plate_radius_mm: msg.r,
      worm_radius_mm: msg.w,
      segments_mm: msg.s,
      food_mm: msg.f,
    };

    let dtSinceLast = 0;
    if (lastMsgAtMs > 0) {
      dtSinceLast = now - lastMsgAtMs;
      if (dtSinceLast > 2 && dtSinceLast < 800) {
        tickMsEma = tickMsEma * 0.72 + dtSinceLast * 0.28;
      }
    }
    lastMsgAtMs = now;
    // Drive blend length from *actual* spacing so motion fills the gap (~80ms), not ~16ms.
    blendSpanMs =
      dtSinceLast > 2
        ? Math.max(24, Math.min(600, dtSinceLast))
        : Math.max(32, Math.min(400, tickMsEma));

    if (targetState !== null) {
      if (incoming.tick < targetState.tick) {
        originState = cloneVisualState(incoming);
      } else {
        originState = cloneVisualState(targetState);
      }
    } else {
      originState = cloneVisualState(incoming);
    }
    targetState = incoming;
    blendStartMs = now;

    if (Array.isArray(msg.c) && msg.c.length >= 2) {
      trajectoryMm.push([Number(msg.c[0]), Number(msg.c[1])]);
      while (trajectoryMm.length > TRAJECTORY_MAX) trajectoryMm.shift();
    }
    const k = Number(msg.k);
    if (Number.isFinite(k)) {
      if (tpsPrevK >= 0 && k > tpsPrevK) {
        tpsAccTicks += k - tpsPrevK;
      }
      tpsPrevK = k;
    }
    setHudTickSimFromK(msg.k);
    if (!viewFitted && msg.r) {
      scale = (Math.min(wormCssW, wormCssH) / (2 * msg.r)) * 0.88;
      cx = 0;
      cy = 0;
      viewFitted = true;
    }

    if (Array.isArray(msg.S)) {
      lastNeuralS = msg.S.map(Number);
    }
    if (Array.isArray(msg.F)) {
      lastNeuralF = msg.F.map((v) => (Number(v) ? 1 : 0));
    }
    if (Array.isArray(msg.R)) {
      lastNeuralR = msg.R.map(Number);
    }

  }

  function connect() {
    statusEl.textContent = "Connecting to " + WS_URL + "…";
    statusEl.className = "";
    const ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      statusEl.textContent = "Connected";
      statusEl.className = "ok";
      if (onlineEl) onlineEl.textContent = "… online";
      trajectoryMm.length = 0;
      targetState = null;
      originState = null;
      lastMsgAtMs = 0;
      tickMsEma = DEFAULT_TICK_MS;
      blendSpanMs = DEFAULT_TICK_MS;
      viewFitted = false;
      layoutAx = null;
      layoutAy = null;
      layoutNames = null;
      neuronMeta = null;
      lastNeuralS = [];
      lastNeuralF = [];
      lastNeuralR = [];
      lastPresenceN = -1;
      tpsPrevK = -1;
      tpsAccTicks = 0;
      if (tpsEl) tpsEl.textContent = "—";
      if (simSpsEl) simSpsEl.textContent = "—";
      setHudTickSimFromK(-1);
      syncAlertsToggleLabel();
    };
    ws.onclose = () => {
      statusEl.textContent = "Disconnected (retry in 3s)";
      statusEl.className = "err";
      if (onlineEl) onlineEl.textContent = "— online";
      setHudTickSimFromK(-1);
      if (tpsEl) tpsEl.textContent = "—";
      if (simSpsEl) simSpsEl.textContent = "—";
      setTimeout(connect, 3000);
    };
    ws.onerror = () => {
      statusEl.textContent = "WebSocket error";
      statusEl.className = "err";
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.p !== PROTOCOL) return;
        if (msg.t === "h") {
          if (msg.L && Array.isArray(msg.L.ax) && Array.isArray(msg.L.ay)) {
            layoutAx = msg.L.ax.map(Number);
            layoutAy = msg.L.ay.map(Number);
            layoutNames = Array.isArray(msg.L.nm) ? msg.L.nm : null;
          }
          neuronMeta = Array.isArray(msg.M) ? msg.M : null;
        } else if (msg.t === "s") {
          applyStateMsg(msg);
        } else if (msg.t === "fa" || msg.t === "fr" || msg.t === "fe") {
          showFoodEventToasts(msg);
        } else if (msg.t === "u" && typeof msg.n === "number") {
          applyPresenceCount(msg.n);
        }
      } catch (_) {
        /* ignore */
      }
    };

    window._ws = ws;
  }

  function animFrame(now) {
    requestAnimationFrame(animFrame);
    draw(now);
    drawNeural();
    syncNeuralTooltipFromHover();
  }

  canvas.addEventListener("contextmenu", (e) => e.preventDefault());

  canvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const sx = ((e.clientX - rect.left) / rect.width) * wormCssW;
      const sy = ((e.clientY - rect.top) / rect.height) * wormCssH;
      const factor = e.deltaY > 0 ? 0.92 : 1.08;
      applyZoomAtCss(sx, sy, factor);
    },
    { passive: false }
  );

  canvas.addEventListener(
    "pointerdown",
    (e) => {
      if (e.pointerType === "touch") {
        wormPtr.set(e.pointerId, { clientX: e.clientX, clientY: e.clientY });
      }

      if (e.pointerType === "mouse") {
        if (e.button === 1 || (e.button === 0 && e.shiftKey)) {
          panning = true;
          panPointerId = e.pointerId;
          panStartX = e.clientX;
          panStartY = e.clientY;
          panOrigCx = cx;
          panOrigCy = cy;
          try {
            canvas.setPointerCapture(e.pointerId);
          } catch (_) {}
          e.preventDefault();
          return;
        }
        if (e.button === 0 && !e.shiftKey) {
          const [sx, sy] = clientToWormCss(e.clientX, e.clientY);
          const [wx, wy] = screenToWorld(sx, sy);
          sendFoodAddWorld(wx, wy);
          e.preventDefault();
          return;
        }
        if (e.button === 2) {
          const [sx, sy] = clientToWormCss(e.clientX, e.clientY);
          const [wx, wy] = screenToWorld(sx, sy);
          sendFoodRemoveWorld(wx, wy);
          e.preventDefault();
          return;
        }
        return;
      }

      if (e.pointerType === "touch") {
        if (wormPtr.size === 2) {
          resetTouchOneFinger();
          pinchPrevDist = 0;
          try {
            canvas.setPointerCapture(e.pointerId);
          } catch (_) {}
          e.preventDefault();
          return;
        }
        if (wormPtr.size === 1) {
          touchDownId = e.pointerId;
          touchDownClientX = e.clientX;
          touchDownClientY = e.clientY;
          touchDownAt = performance.now();
          touchPanSlopPassed = false;
          touchLongPressSent = false;
          clearTouchLongPress();
          touchLongPressTimer = window.setTimeout(() => {
            touchLongPressTimer = 0;
            if (touchDownId !== e.pointerId || touchLongPressSent) return;
            if (wormPtr.size !== 1) return;
            if (touchPanSlopPassed) return;
            const [sx, sy] = clientToWormCss(touchDownClientX, touchDownClientY);
            const [wx, wy] = screenToWorld(sx, sy);
            sendFoodRemoveWorld(wx, wy);
            touchLongPressSent = true;
          }, TOUCH_LONG_PRESS_MS);
          try {
            canvas.setPointerCapture(e.pointerId);
          } catch (_) {}
          e.preventDefault();
        }
      }
    },
    { passive: false }
  );

  canvas.addEventListener(
    "pointermove",
    (e) => {
      if (e.pointerType === "touch") {
        const rec = wormPtr.get(e.pointerId);
        if (rec) {
          rec.clientX = e.clientX;
          rec.clientY = e.clientY;
        }
      }

      if (wormPtr.size === 2) {
        const m = wormPinchMetrics();
        if (m && m.dist >= 1) {
          if (pinchPrevDist < 1) {
            pinchPrevDist = Math.max(m.dist, PINCH_MIN_DIST_PX);
          } else {
            const factor = m.dist / pinchPrevDist;
            if (Math.abs(factor - 1) > 0.0015) {
              applyZoomAtCss(m.midSx, m.midSy, factor);
            }
            pinchPrevDist = m.dist;
          }
        }
        e.preventDefault();
        return;
      }

      if (panning && e.pointerId === panPointerId) {
        const dx = e.clientX - panStartX;
        const dy = e.clientY - panStartY;
        cx = panOrigCx - dx / scale;
        cy = panOrigCy + dy / scale;
        return;
      }

      if (
        e.pointerType === "touch" &&
        touchDownId === e.pointerId &&
        wormPtr.size === 1
      ) {
        const dx = e.clientX - touchDownClientX;
        const dy = e.clientY - touchDownClientY;
        const slop2 = TOUCH_TAP_MAX_DIST_PX * TOUCH_TAP_MAX_DIST_PX;
        if (!touchPanSlopPassed && dx * dx + dy * dy > slop2) {
          clearTouchLongPress();
          touchPanSlopPassed = true;
          panStartX = e.clientX;
          panStartY = e.clientY;
          panOrigCx = cx;
          panOrigCy = cy;
        }
        if (touchPanSlopPassed) {
          const pdx = e.clientX - panStartX;
          const pdy = e.clientY - panStartY;
          cx = panOrigCx - pdx / scale;
          cy = panOrigCy + pdy / scale;
        }
        e.preventDefault();
      }
    },
    { passive: false }
  );

  function wormPointerUp(e) {
    const wasTwo = wormPtr.size === 2;
    if (e.pointerType === "touch") {
      wormPtr.delete(e.pointerId);
    }

    if (e.pointerId === panPointerId) {
      panning = false;
      panPointerId = -1;
    }

    if (wasTwo && wormPtr.size < 2) {
      pinchPrevDist = 0;
      resetTouchOneFinger();
    }

    if (e.pointerType === "touch" && e.pointerId === touchDownId) {
      const dur = performance.now() - touchDownAt;
      const dx = e.clientX - touchDownClientX;
      const dy = e.clientY - touchDownClientY;
      const slop2 = TOUCH_TAP_MAX_DIST_PX * TOUCH_TAP_MAX_DIST_PX;
      const moved = dx * dx + dy * dy > slop2;
      if (
        !touchPanSlopPassed &&
        !moved &&
        !touchLongPressSent &&
        dur < TOUCH_TAP_MAX_MS
      ) {
        const [sx, sy] = clientToWormCss(e.clientX, e.clientY);
        const [wx, wy] = screenToWorld(sx, sy);
        sendFoodAddWorld(wx, wy);
      }
      resetTouchOneFinger();
    }

    try {
      canvas.releasePointerCapture(e.pointerId);
    } catch (_) {}
  }

  canvas.addEventListener("pointerup", wormPointerUp);
  canvas.addEventListener("pointercancel", wormPointerUp);

  window.addEventListener("pointerup", (e) => {
    if (e.pointerId === panPointerId) {
      panning = false;
      panPointerId = -1;
    }
  });

  window.addEventListener("resize", resize);
  if (window.visualViewport) {
    window.visualViewport.addEventListener(
      "resize",
      invalidatePhysicalCmCache
    );
    window.visualViewport.addEventListener(
      "scroll",
      invalidatePhysicalCmCache
    );
  }

  function neuralPointerMove(e) {
    neuralHoverClientX = e.clientX;
    neuralHoverClientY = e.clientY;
    if (!neuralFineHoverCapable()) {
      hoverNeuronIdx = -1;
      neuralCanvas.style.cursor = "default";
      if (neuralTooltipEl) neuralTooltipEl.style.display = "none";
      return;
    }
    const rect = neuralCanvas.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * neuralCssW;
    const my = ((e.clientY - rect.top) / rect.height) * neuralCssH;
    const idx = pickNeuronAtCss(mx, my);
    hoverNeuronIdx = idx;
    neuralCanvas.style.cursor = idx >= 0 ? "pointer" : "default";
    syncNeuralTooltipFromHover();
  }

  neuralCanvas.addEventListener("pointermove", neuralPointerMove);

  neuralCanvas.addEventListener("pointerleave", () => {
    hoverNeuronIdx = -1;
    neuralCanvas.style.cursor = "default";
    if (neuralTooltipEl) neuralTooltipEl.style.display = "none";
    neuralDownAt = 0;
  });

  neuralCanvas.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    neuralDownClientX = e.clientX;
    neuralDownClientY = e.clientY;
    neuralDownAt = performance.now();
  });

  neuralCanvas.addEventListener("pointercancel", () => {
    neuralDownAt = 0;
  });

  neuralCanvas.addEventListener("pointerup", (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (!neuralDownAt) return;
    const dur = performance.now() - neuralDownAt;
    const dx = e.clientX - neuralDownClientX;
    const dy = e.clientY - neuralDownClientY;
    neuralDownAt = 0;
    if (dx * dx + dy * dy > 20 * 20) return;
    if (dur > 700) return;
    const rect = neuralCanvas.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * neuralCssW;
    const my = ((e.clientY - rect.top) / rect.height) * neuralCssH;
    const idx = pickNeuronAtCss(mx, my);
    if (idx >= 0) {
      e.preventDefault();
      openNeuronModal(idx);
    }
  });

  const neuronModalRoot = document.getElementById("neuron-modal");
  if (neuronModalRoot) {
    neuronModalRoot.addEventListener("click", (e) => {
      const t = e.target;
      if (
        t instanceof HTMLElement &&
        t.getAttribute("data-close-neuron-modal") === "1"
      ) {
        closeNeuronModal();
      }
    });
  }

  const alertsBtn = document.getElementById("alerts-toggle");
  if (alertsBtn) {
    alertsBtn.addEventListener("click", () => {
      if (typeof Notification === "undefined") {
        showToast("Notifications not supported in this browser", {
          os: false,
          title: "Alerts",
        });
        return;
      }
      if (alertsActive()) {
        alertsWanted = false;
        try {
          localStorage.setItem(LS_ALERTS, "0");
        } catch (_) {}
        syncAlertsToggleLabel();
        showToast("Desktop alerts off (in-page toasts only)", { os: false });
        return;
      }
      if (Notification.permission === "denied") {
        showToast("Notifications blocked — allow this site in browser settings", {
          os: false,
          title: "Alerts",
        });
        return;
      }
      Notification.requestPermission().then((p) => {
        if (p === "granted") {
          alertsWanted = true;
          try {
            localStorage.setItem(LS_ALERTS, "1");
          } catch (_) {}
        } else {
          alertsWanted = false;
          try {
            localStorage.setItem(LS_ALERTS, "0");
          } catch (_) {}
        }
        syncAlertsToggleLabel();
        if (p === "granted") {
          showToast("Desktop alerts on — tray notifications + sound for food and viewer join/leave", {
            title: "C. elegans live",
          });
        } else {
          showToast("Notification permission not granted", { os: false });
        }
      });
    });
  }
  syncAlertsToggleLabel();

  (function initBackgroundMusic() {
    if (NO_BG_MUSIC) return;
    const a = document.getElementById("bg-audio");
    if (!a || !(a instanceof HTMLAudioElement)) return;
    a.volume = 0.32;

    let srcWired = false;

    const detach = () => {
      window.removeEventListener("pointerdown", tryStart);
      window.removeEventListener("keydown", tryStart);
    };

    const tryStart = () => {
      if (!srcWired) {
        a.src = "bg.m4a";
        srcWired = true;
      }
      if (!a.paused) {
        detach();
        return;
      }
      void a.play().then(detach).catch(() => {});
    };

    window.addEventListener("pointerdown", tryStart, { passive: true });
    window.addEventListener("keydown", tryStart, { passive: true });
    requestAnimationFrame(() => {
      requestAnimationFrame(tryStart);
    });
  })();

  resize();
  connect();
  requestAnimationFrame(animFrame);
})();
