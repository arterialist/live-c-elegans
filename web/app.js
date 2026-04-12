/**
 * C. elegans live viewer — WebSocket + canvas (pan/zoom, worm spine + parts).
 * Protocol v2: short JSON keys (see README). Trajectory built locally from com (c).
 *
 * Rendering: CSS-pixel space + DPR bitmap; world→view via one canvas transform;
 * continuous requestAnimationFrame for FPS display + smooth lerp between sim ticks.
 */
(function () {
  const DEFAULT_WS_URL = "ws://127.0.0.1:8765";
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

  const params = new URLSearchParams(window.location.search);
  const WS_URL = params.get("ws") || DEFAULT_WS_URL;

  const canvas = document.getElementById("c");
  const ctx =
    canvas.getContext("2d", { alpha: false, desynchronized: true }) ||
    canvas.getContext("2d");
  const statusEl = document.getElementById("status");
  const tickEl = document.getElementById("tick");
  const fpsEl = document.getElementById("fps");

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

  /** CSS layout size (not bitmap); updated in resize only */
  let cssW = 800;
  let cssH = 600;
  let dpr = 1;

  let fpsAccFrames = 0;
  let fpsAccStart = 0;

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
    dpr = window.devicePixelRatio || 1;
    cssW = wrap.clientWidth;
    cssH = wrap.clientHeight;
    canvas.width = Math.floor(cssW * dpr);
    canvas.height = Math.floor(cssH * dpr);
    canvas.style.width = cssW + "px";
    canvas.style.height = cssH + "px";
  }

  function screenToWorld(sx, sy) {
    const wx = cx + (sx - cssW / 2) / scale;
    const wy = cy - (sy - cssH / 2) / scale;
    return [wx, wy];
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
      const fps = (fpsAccFrames * 1000) / (now - fpsAccStart);
      fpsEl.textContent = Math.round(fps) + " fps";
      fpsAccFrames = 0;
      fpsAccStart = now;
    }

    const lastState = getRenderState(now);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#1a1d24";
    ctx.fillRect(0, 0, cssW, cssH);

    if (!lastState || !lastState.segments_mm) {
      ctx.fillStyle = "#888";
      ctx.font = "14px system-ui";
      ctx.fillText("Waiting for simulation…", 16, 28);
      return;
    }

    const pr = lastState.plate_radius_mm ?? plateRadiusMm;
    plateRadiusMm = pr;
    const wormR = lastState.worm_radius_mm ?? 0.04;
    const segs = lastState.segments_mm;

    ctx.save();
    ctx.translate(cssW / 2, cssH / 2);
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
    tickEl.textContent = "tick " + msg.k;
    if (!viewFitted && msg.r) {
      scale = (Math.min(cssW, cssH) / (2 * msg.r)) * 0.88;
      cx = 0;
      cy = 0;
      viewFitted = true;
    }
  }

  function connect() {
    statusEl.textContent = "Connecting to " + WS_URL + "…";
    statusEl.className = "";
    const ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      statusEl.textContent = "Connected";
      statusEl.className = "ok";
      trajectoryMm.length = 0;
      targetState = null;
      originState = null;
      lastMsgAtMs = 0;
      tickMsEma = DEFAULT_TICK_MS;
      blendSpanMs = DEFAULT_TICK_MS;
      viewFitted = false;
    };
    ws.onclose = () => {
      statusEl.textContent = "Disconnected (retry in 3s)";
      statusEl.className = "err";
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
        if (msg.t === "s") {
          applyStateMsg(msg);
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
  }

  canvas.addEventListener("mousedown", (e) => {
    if (e.button === 1 || (e.button === 0 && e.shiftKey)) {
      panning = true;
      panStartX = e.clientX;
      panStartY = e.clientY;
      panOrigCx = cx;
      panOrigCy = cy;
      e.preventDefault();
      return;
    }
    if (!window._ws || window._ws.readyState !== WebSocket.OPEN) return;
    const rect = canvas.getBoundingClientRect();
    const sx = ((e.clientX - rect.left) / rect.width) * cssW;
    const sy = ((e.clientY - rect.top) / rect.height) * cssH;
    const [wx, wy] = screenToWorld(sx, sy);
    const base = { p: PROTOCOL, x: wx, y: wy };
    if (e.button === 0) {
      window._ws.send(JSON.stringify({ ...base, t: "a" }));
    } else if (e.button === 2) {
      window._ws.send(JSON.stringify({ ...base, t: "v" }));
    }
  });

  canvas.addEventListener("mousemove", (e) => {
    if (!panning) return;
    const dx = e.clientX - panStartX;
    const dy = e.clientY - panStartY;
    cx = panOrigCx - dx / scale;
    cy = panOrigCy + dy / scale;
  });

  window.addEventListener("mouseup", () => {
    panning = false;
  });

  canvas.addEventListener("contextmenu", (e) => e.preventDefault());

  canvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const sx = ((e.clientX - rect.left) / rect.width) * cssW;
      const sy = ((e.clientY - rect.top) / rect.height) * cssH;
      const [wmx, wmy] = screenToWorld(sx, sy);
      const factor = e.deltaY > 0 ? 0.92 : 1.08;
      const newScale = Math.min(MAX_SCALE_PX_PER_MM, Math.max(0.25, scale * factor));
      scale = newScale;
      cx = wmx - (sx - cssW / 2) / scale;
      cy = wmy + (sy - cssH / 2) / scale;
    },
    { passive: false }
  );

  window.addEventListener("resize", resize);

  resize();
  connect();
  requestAnimationFrame(animFrame);
})();
