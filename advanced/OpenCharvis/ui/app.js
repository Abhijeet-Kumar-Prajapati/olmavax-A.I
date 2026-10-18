/* ============================================================
   Open Charvis - interface logic
   - 3D holographic core on a raw WebGL canvas (no libraries)
   - talks to the local agent over /api/*
   ============================================================ */

(() => {
  "use strict";

  /* ── tiny helpers ─────────────────────────────────────── */
  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  async function api(path, options) {
    const res = await fetch(path, options);
    const data = await res.json().catch(() => ({ error: "bad response" }));
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  const post = (path, body) =>
    api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let toastTimer = null;
  function toast(message, bad = false) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.toggle("bad", bad);
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 4200);
  }

  /* ── WebGL holographic core ───────────────────────────── */
  const Halo = (() => {
    const canvas = $("#holo");
    const gl = canvas.getContext("webgl", { antialias: true, alpha: true });
    if (!gl) return { resize() {}, pulse() {} };   // graceful: no WebGL, no 3D

    const VERT = `
      attribute vec2 aPos;
      uniform float uTime, uMood, uAspect;
      void main() {
        float r = length(aPos);
        float t = uTime;
        // ripple driven by mood: 0 calm, 1 busy
        float wave = sin(r * 26.0 - t * (1.6 + uMood * 3.4)) * 0.016 * (0.35 + uMood);
        float spin = t * (0.06 + uMood * 0.16);
        float c = cos(spin), s = sin(spin);
        vec2 p = vec2(aPos.x * c - aPos.y * s, aPos.x * s + aPos.y * c);
        // squash so the disc stays circular on wide screens
        p.y /= max(uAspect, 0.0001);
        p.y *= max(uAspect, 0.0001);
        p += p * wave;
        gl_Position = vec4(p, 0.0, 1.0);
      }`;

    const FRAG = `
      precision highp float;
      uniform float uTime, uMood;
      varying float vR;
      void main() {
        float r = length(vec2(gl_PointCoord.x, gl_PointCoord.y));
        // concentric scan rings + angular sweep, the classic holo look
        float rings = 0.5 + 0.5 * sin(r * 78.0 - uTime * 2.2);
        float sweep = 0.5 + 0.5 * sin(atan(gl_PointCoord.y, gl_PointCoord.x) * 3.0 - uTime * 0.9);
        float edge  = smoothstep(1.0, 0.72, r);
        vec3 cyan   = vec3(0.20, 0.88, 1.00);
        vec3 violet = vec3(0.48, 0.36, 1.00);
        vec3 col = mix(cyan, violet, sweep * 0.7 + rings * 0.3);
        float alpha = edge * (0.16 + 0.34 * rings + 0.14 * sweep) * (0.55 + uMood * 0.65);
        // brighter hot core
        alpha += smoothstep(0.30, 0.0, r) * (0.16 + uMood * 0.22);
        gl_FragColor = vec4(col * (0.85 + uMood * 0.5), alpha);
      }`;

    function compile(type, src) {
      const sh = gl.createShader(type);
      gl.shaderSource(sh, src);
      gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
        console.warn("shader:", gl.getShaderInfoLog(sh));
        gl.deleteShader(sh);
        return null;
      }
      return sh;
    }

    const vs = compile(gl.VERTEX_SHADER, VERT);
    const fs = compile(gl.FRAGMENT_SHADER, FRAG);
    if (!vs || !fs) return { resize() {}, pulse() {} };

    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      console.warn("link:", gl.getProgramInfoLog(prog));
      return { resize() {}, pulse() {} };
    }
    gl.useProgram(prog);

    // Build a disc of points
    const RINGS = 46, PER = 96;
    const verts = [];
    for (let i = 0; i < RINGS; i++) {
      const rad = (i + 1) / RINGS * 0.86;
      for (let j = 0; j < PER; j++) {
        const ang = (j / PER) * Math.PI * 2;
        verts.push(Math.cos(ang) * rad, Math.sin(ang) * rad);
      }
    }

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(verts), gl.STATIC_DRAW);

    const loc = gl.getAttribLocation(prog, "aPos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const uTime   = gl.getUniformLocation(prog, "uTime");
    const uMood   = gl.getUniformLocation(prog, "uMood");
    const uAspect = gl.getUniformLocation(prog, "uAspect");

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE);
    gl.clearColor(0, 0, 0, 0);

    let mood = 0.18, targetMood = 0.18, running = true, raf = 0;
    let light = true;   // matches the light theme

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.floor(canvas.clientWidth * dpr);
      const h = Math.floor(canvas.clientHeight * dpr);
      if (canvas.width === w && canvas.height === h) return;
      canvas.width = w;
      canvas.height = h;
      gl.viewport(0, 0, w, h);
    }

    function frame(t) {
      if (!running) return;
      resize();
      mood += (targetMood - mood) * 0.06;

      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.uniform1f(uTime, t / 1000);
      gl.uniform1f(uMood, mood);
      gl.uniform1f(uAspect, canvas.height / Math.max(1, canvas.width));
      gl.drawArrays(gl.POINTS, 0, RINGS * PER);
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);

    // Pause when the tab is hidden so the agent is not burning CPU.
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(raf);
      } else if (!running) {
        running = true;
        raf = requestAnimationFrame(frame);
      }
    });

    window.addEventListener("resize", resize);
    resize();

    return {
      /** 0 = idle, 1 = working hard */
      pulse(level) {
        targetMood = Math.max(0.12, Math.min(1, level));
        setTimeout(() => { targetMood = 0.18; }, 1600);
      },
      setTheme(isLight) { light = isLight; },
    };
  })();

  /* ── chat ─────────────────────────────────────────────── */
  const log = $("#log");

  function scrollDown() {
    // Only follow the conversation when the reader is already at the
    // bottom, so scrolling back to re-read something is not fought.
    const near = log.scrollHeight - log.scrollTop - log.clientHeight < 140;
    if (near || stickToBottom) {
      log.scrollTop = log.scrollHeight;
      stickToBottom = true;
    } else {
      stickToBottom = false;
    }
  }

  let stickToBottom = true;
  log.addEventListener("scroll", () => {
    stickToBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
  });

  /* Renders the subset of markdown the agent actually produces: fenced
     code, inline code, bold, and bullet lists. Everything is escaped
     first, so a reply containing HTML is shown, not executed. */
  const MD_MARK = "@@";

  function md(text) {
    const safe = esc(text || "");
    const blocks = [];
    // Pull fenced code out first so nothing inside it gets styled.
    const held = safe.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, body) => {
      blocks.push(`<pre><code>${body.replace(/\n+$/, "")}</code></pre>`);
      return MD_MARK + (blocks.length - 1) + MD_MARK;
    });
    return held
      .replace(/@@(\d+)@@/g, (_, i) => blocks[Number(i)] || "")
      .replace(/`([^`\n]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|\n)[-*] +(.+)/g, "$1• $2");
  }

  /* Plain text for speech - strips the markup so it is not read aloud. */
  function stripMd(text) {
    return (text || "")
      .replace(/```(\w*)\n?/g, " ")
      .replace(/\*\*|`/g, "")
      .replace(/@@\d+@@/g, " code ")
      .replace(/^• /gm, "");
  }

  function bubble(who, text, meta = {}) {
    const wrap = document.createElement("div");
    const cls = meta.blocked ? "bot blocked" : meta.needs_confirmation ? "bot needs-confirm" : who === "bot" ? "bot" : "user";
    wrap.className = `msg ${cls}`;

    // Kept deliberately short. The intent name is useful when something
    // goes wrong, but as a permanent label on every reply it is just
    // noise, so it lives in the tooltip instead.
    const tags = [];
    if (meta.tool)    tags.push(`<span class="tag tool">${esc(meta.tool)}</span>`);
    if (meta.offline) tags.push(`<span class="tag offline">offline</span>`);
    if (meta.security && meta.security !== "allow") {
      tags.push(`<span class="tag offline">${esc(meta.security)}</span>`);
    }

    const detail = [
      meta.intent ? `intent: ${meta.intent}` : "",
      meta.memory ? `${meta.memory} memories recalled` : "",
      `${(meta.elapsed || 0).toFixed(2)}s`,
    ].filter(Boolean).join(" · ");

    wrap.innerHTML = `
      <div class="who" aria-label="${who === "user" ? "you" : "charvis"}"></div>
      <div class="bubble">${md(text)}</div>
      ${tags.length ? `<div class="foot" title="${esc(detail)}">${tags.join("")}<span>${(meta.elapsed || 0).toFixed(2)}s</span></div>` : ""}`;
    log.appendChild(wrap);
    scrollDown();
    return wrap;
  }

  let thinkingNode = null;
  function showThinking() {
    hideThinking();
    thinkingNode = document.createElement("div");
    thinkingNode.className = "msg bot";
    thinkingNode.innerHTML =
      `<div class="who"></div>
       <div class="bubble"><span class="dots"><span></span><span></span><span></span></span></div>`;
    log.appendChild(thinkingNode);
    scrollDown();
  }
  function hideThinking() {
    if (thinkingNode) { thinkingNode.remove(); thinkingNode = null; }
  }

  let busy = false;
  let currentSession = "default";

  async function send(text) {
    if (busy || !text.trim()) return;
    busy = true;
    hideWelcome();
    retireStarters();
    $("#sendBtn").style.opacity = ".45";
    bubble("user", text);
    $("#input").value = "";
    autosize();

    // Anything attached is analysed first, so the answer is grounded in
    // the real file rather than in a guess about it.
    let context = "";
    if (attachments.length) {
      const files = attachments.splice(0);
      renderAttachments();
      showThinking();
      const parts = [];
      for (const f of files) {
        if (!f.path) {
          parts.push(`${f.name}: could not be uploaded`);
          continue;
        }
        const r = await post("/api/tool", { name: "file.analyze", args: { path: f.path } })
          .catch(() => null);
        if (r?.output) {
          const o = r.output;
          parts.push(
            `${o.name}: ${o.kind}, ${o.lines ?? o.rows ?? o.pixels ?? "?"} ` +
            `${o.lines ? "lines" : o.rows ? "rows" : o.pixels ? "px" : ""}` +
            (o.columns ? `, columns: ${o.columns.join(", ")}` : "") +
            (o.functions ? `, functions: ${o.functions.join(", ")}` : "") +
            (o.headings ? `, headings: ${o.headings.slice(0, 8).join(" | ")}` : "")
          );
        } else {
          parts.push(`${f.name}: could not be analysed`);
        }
      }
      if (parts.length) context = "\n\n[attached files]\n" + parts.join("\n");
    }

    const payloadText = text + context;
    showThinking();
    Halo.pulse(0.85);

    let streamed = false;
    let liveNode = null;
    let meta = null;

    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: payloadText, source: "web", session: currentSession }),
      });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data:")) continue;
          let evt;
          try { evt = JSON.parse(line.slice(5)); } catch { continue; }

          if (evt.event === "heartbeat") continue;
          if (evt.event === "final") { meta = evt; continue; }
          if (evt.event === "error") {
            hideThinking();
            bubble("bot", `Error: ${evt.message}`, { blocked: true });
          }
          if (evt.event !== "delta") continue;

          if (!streamed) {
            hideThinking();
            streamed = true;
            liveNode = bubble("bot", "", {});
            liveNode.querySelector('.bubble').classList.add('streaming');
          }
          liveNode.querySelector('.bubble').textContent += evt.text;
          scrollDown();
        }
      }

      hideThinking();
      if (streamed && liveNode) {
        const node = liveNode;
        const el = node.querySelector('.bubble');
        const plain = el.textContent;
        el.classList.remove('streaming');
        // Re-render the finished text as markdown. Streaming appends plain
        // text for speed; this swaps in the formatting once nothing more
        // is coming.
        el.innerHTML = md(plain);
        // Same deliberately short footer as bubble() uses elsewhere.
        const tags = [];
        if (meta?.tool)    tags.push(`<span class="tag tool">${esc(meta.tool)}</span>`);
        if (meta?.offline) tags.push(`<span class="tag offline">offline</span>`);
        const detail = [
          meta?.intent ? `intent: ${meta.intent}` : "",
          meta?.memories ? `${meta.memories} memories recalled` : "",
          `${(meta?.elapsed ?? 0).toFixed(2)}s`,
        ].filter(Boolean).join(" · ");
        const foot = document.createElement('div');
        foot.className = 'foot';
        foot.title = detail;
        foot.innerHTML = tags.join('') + `<span>${(meta?.elapsed ?? 0).toFixed(2)}s</span>`;
        node.appendChild(foot);
        Halo.pulse(0.3);
        speak(stripMd(plain));

        if (meta?.intent === "shutdown") {
          setTimeout(() => {
            bubble("bot",
              "Agent powered down. Everything is saved.\nRestart it with:  charvis ui");
            $("#linkDot").classList.remove("online");
          }, 900);
        }
      } else if (!streamed) {
        // Nothing streamed (an immediate refusal, for instance).
        const reply = await post("/api/chat", { text: payloadText, source: "web", session: currentSession });
        hideThinking();
        bubble("bot", reply.text, {
          tool: reply.tool, intent: reply.intent, offline: reply.offline,
          memory: (reply.memories_used || []).length, elapsed: reply.elapsed,
          blocked: reply.security === "block",
          needs_confirmation: reply.needs_confirmation,
        });
        speak(reply.text);
      }
    } catch (err) {
      hideThinking();
      bubble("bot", `I could not reach the agent: ${err.message}`, { blocked: true });
    } finally {
      busy = false;
      $("#sendBtn").style.opacity = "1";
    }
  }

  /* ── composer ─────────────────────────────────────────── */
  const input = $("#input");

  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(input.scrollHeight, 190) + "px";
  }
  input.addEventListener("input", autosize);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input.value); }
  });
  $("#sendBtn").addEventListener("click", () => send(input.value));

  const STARTERS = [
    "status", "who are you", "security report",
    "remember that my wifi password is on the fridge",
    "draw an image of a neon city", "what can you do",
  ];
  function renderStarters() {
    const box = $("#suggestions");
    box.innerHTML = STARTERS
      .map((s) => `<button>${esc(s)}</button>`).join("");
    $$("#suggestions button").forEach((b) =>
      b.addEventListener("click", () => send(b.textContent)));
    // Only useful before the first exchange. After that the conversation
    // itself is the better guide.
    if (!$("#log").children.length) box.classList.add("show");
  }

  function retireStarters() {
    $("#suggestions").classList.remove("show");
  }

  /* ── live voice ─────────────────────────────────────────────
     A real turn-taking loop rather than a push-to-talk bar:

       listen → detect silence → send → speak the answer →
       fall back to listening → repeat

     Two details make it feel like a conversation. The orb is driven
     by the actual microphone level, not a canned animation. And while
     it is speaking, anything you say cancels the speech immediately,
     so you can cut in mid-sentence. */
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const micBtn = $("#micBtn");
  const speakBtn = $("#speakBtn");

  const liveOverlay = $("#liveOverlay");
  const orbCanvas = $("#orbCanvas");
  const orbCtx = orbCanvas.getContext("2d");
  const liveState = $("#liveState");
  const liveSaid = $("#liveSaid");
  const liveReply = $("#liveReply");
  const liveHint = $("#liveHint");
  const liveMute = $("#liveMute");

  let speakReplies = localStorage.getItem("charvis.speak") !== "0";

  // How long a pause means "I have finished speaking". Tuned by feel:
  // long enough that a pause between clauses does not cut you off,
  // short enough that the reply feels immediate.
  const SILENCE_MS = 1100;
  const BARGE_IN_DB = -42;   // level above which we assume you are talking over me

  const live = {
    on: false,
    muted: false,
    rec: null,
    heard: "",        // committed text for the turn in progress
    pending: "",      // interim words, not yet final
    timer: null,
    speaking: false,
    thinking: false,
    busy: false,
  };

  // -- microphone level, for the orb ------------------------------
  const mic = { audio: null, ctx: null, analyser: null, data: null, level: 0 };

  async function startMicMeter() {
    if (mic.ctx) { resumeMicMeter(); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      ctx.createMediaStreamSource(stream).connect(analyser);
      mic.audio = stream;
      mic.ctx = ctx;
      mic.analyser = analyser;
      mic.data = new Uint8Array(analyser.frequencyBinCount);
    } catch {
      mic.analyser = null;   // no meter; the orb falls back to a gentle pulse
    }
  }

  function resumeMicMeter() {
    if (mic.ctx && mic.ctx.state === "suspended") mic.ctx.resume().catch(() => {});
  }

  function micLevel() {
    if (!mic.analyser) return 0;
    mic.analyser.getByteTimeDomainData(mic.data);
    let peak = 0;
    for (let i = 0; i < mic.data.length; i++) {
      const v = Math.abs(mic.data[i] - 128) / 128;
      if (v > peak) peak = v;
    }
    mic.level = mic.level * 0.6 + peak * 0.4;
    return mic.level;
  }

  function stopMicMeter() {
    mic.audio?.getTracks().forEach((t) => t.stop());
    mic.ctx?.close().catch(() => {});
    mic.audio = mic.ctx = mic.analyser = mic.data = null;
    mic.level = 0;
  }

  // -- the orb ----------------------------------------------------
  let orbRAF = null;
  let orbPhase = 0;

  function drawOrb() {
    const w = orbCanvas.width, h = orbCanvas.height;
    const cx = w / 2, cy = h / 2;
    const base = Math.min(w, h) * 0.30;

    // While speaking there is no usable mic level (echo), so drive the
    // orb from a smooth synthetic wave instead of a dead flat line.
    const level = live.speaking ? 0.55 + Math.sin(orbPhase * 2.1) * 0.22 : micLevel();
    orbPhase += 0.045;

    orbCtx.clearRect(0, 0, w, h);

    const accent = live.muted ? "127,140,160" : "52,224,255";
    const bars = 96;
    for (let i = 0; i < bars; i++) {
      const t = i / bars;
      const angle = t * Math.PI * 2 - Math.PI / 2;

      // A travelling wave around the ring, amplitude from the mic.
      const wave = Math.sin(t * Math.PI * 8 - orbPhase * 3) * 0.35 + 1;
      const amp = base * (0.34 + level * 2.3) * wave;

      const inner = base * 0.82;
      const x1 = cx + Math.cos(angle) * inner;
      const y1 = cy + Math.sin(angle) * inner;
      const x2 = cx + Math.cos(angle) * (inner + amp);
      const y2 = cy + Math.sin(angle) * (inner + amp);

      orbCtx.beginPath();
      orbCtx.moveTo(x1, y1);
      orbCtx.lineTo(x2, y2);
      orbCtx.strokeStyle = `rgba(${accent},${0.25 + level * 0.7})`;
      orbCtx.lineWidth = 2.4;
      orbCtx.lineCap = "round";
      orbCtx.stroke();
    }

    // The core, brighter and pulsing with the same level.
    const glow = orbCtx.createRadialGradient(cx, cy, 0, cx, cy, base * 1.5);
    glow.addColorStop(0, `rgba(${accent},${0.34 + level * 0.4})`);
    glow.addColorStop(1, `rgba(${accent},0)`);
    orbCtx.fillStyle = glow;
    orbCtx.beginPath();
    orbCtx.arc(cx, cy, base * 1.5, 0, Math.PI * 2);
    orbCtx.fill();

    orbRAF = requestAnimationFrame(drawOrb);
  }

  function setLiveState(text, kind) {
    liveState.textContent = text;
    liveOverlay.classList.toggle("is-speaking", kind === "speaking");
    liveOverlay.classList.toggle("is-thinking", kind === "thinking");
    liveOverlay.classList.toggle("is-muted", kind === "muted");
  }

  // -- speech out ------------------------------------------------
  function speak(text) {
    if (!speakReplies || !text || !("speechSynthesis" in window)) return Promise.resolve();
    window.speechSynthesis.cancel();
    const clean = String(text)
      .replace(/```[\s\S]*?```/g, " a code block ")
      .replace(/https?:\/\/\S+/g, " a link ")
      .replace(/[*_#`|]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 700);
    if (!clean) return Promise.resolve();

    return new Promise((resolve) => {
      const utterance = new SpeechSynthesisUtterance(clean);
      utterance.rate = 1.04;
      utterance.pitch = 1.0;
      const voices = window.speechSynthesis.getVoices();
      const preferred =
        voices.find((v) => v.lang?.startsWith("en-IN")) ||
        voices.find((v) => v.lang?.startsWith("en")) ||
        voices.find((v) => v.localService);
      if (preferred) utterance.voice = preferred;

      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        resolve();
      };
      utterance.onend = finish;
      utterance.onerror = finish;
      window.speechSynthesis.speak(utterance);

      // Chrome occasionally drops onend. Do not let the loop hang on it.
      setTimeout(finish, Math.min(20000, 1800 + clean.length * 75));
    });
  }

  // -- speech in -------------------------------------------------
  function beginRecognition() {
    if (!live.on || live.rec || live.muted) return;
    const rec = new SR();
    rec.lang = "en-IN";
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    live.rec = rec;

    rec.onresult = (event) => {
      if (!live.on) return;
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const chunk = event.results[i][0].transcript;
        if (event.results[i].isFinal) live.heard += chunk + " ";
        else interim += chunk;
      }
      live.pending = interim.trim();

      // Barge-in: the moment there is a final transcript while the agent
      // is talking, cut the speech off and listen.
      if (live.speaking && live.heard.trim()) {
        window.speechSynthesis.cancel();
        live.speaking = false;
      }

      const shown = (live.heard + " " + live.pending).trim();
      liveSaid.textContent = shown;
      setLiveState("Listening", "listening");

      // Restart the silence timer on every new word.
      scheduleSend();
    };

    rec.onerror = (event) => {
      if (event.error === "no-speech" || event.error === "aborted") return;
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        toast("Microphone blocked. Allow it from the address bar.", true);
        closeLive();
      }
    };

    rec.onend = () => {
      live.rec = null;
      // Chrome ends the session on its own after a pause; pick it back up.
      if (live.on && !live.muted) {
        setTimeout(() => {
          if (live.on && !live.rec) { try { beginRecognition(); } catch { /* browser said no */ } }
        }, 220);
      }
    };

    try { rec.start(); } catch { live.rec = null; }
  }

  function scheduleSend() {
    clearTimeout(live.timer);
    live.timer = setTimeout(flushTurn, SILENCE_MS);
  }

  // -- the turn --------------------------------------------------
  async function flushTurn() {
    clearTimeout(live.timer);
    const said = (live.heard + " " + live.pending).trim();
    live.heard = "";
    live.pending = "";
    if (!said || live.busy) return;

    live.busy = true;
    live.thinking = true;
    liveSaid.textContent = said;
    liveReply.textContent = "";
    setLiveState("Thinking", "thinking");
    liveHint.textContent = "Working on it…";

    try {
      const reply = await post("/api/chat", {
        text: said, source: "voice", session: currentSession,
      });
      const text = (reply && reply.text) || "I could not work that out.";
      liveReply.textContent = text;

      // Record it in the transcript so the chat panel keeps the record.
      bubble("user", said);
      bubble("bot", text, {
        tool: reply.tool, intent: reply.intent, offline: reply.offline,
        memory: (reply.memories_used || []).length, elapsed: reply.elapsed,
      });
      hideWelcome();

      live.thinking = false;
      live.speaking = true;
      setLiveState("Speaking", "speaking");
      await speak(text);
      live.speaking = false;
      liveSaid.textContent = "";
      setLiveState("Listening", "listening");
      liveHint.textContent = "Start speaking. I answer when you stop.";
    } catch {
      liveReply.textContent = "Something went wrong reaching the agent.";
      setLiveState("Error", "thinking");
    } finally {
      live.busy = false;
      live.thinking = false;
      live.speaking = false;
    }
  }

  // -- open / close ----------------------------------------------
  async function openLive() {
    if (live.on) return;
    if (!SR) {
      toast("This browser has no speech recognition. Use Chrome or Edge.", true);
      return;
    }
    live.on = true;
    live.muted = false;
    live.heard = "";
    live.pending = "";
    liveSaid.textContent = "";
    liveReply.textContent = "";
    liveMute.classList.remove("on");
    liveOverlay.hidden = false;
    document.body.classList.add("live-open");
    setLiveState("Listening", "listening");
    liveHint.textContent = "Start speaking. I answer when you stop.";
    orbRAF = requestAnimationFrame(drawOrb);

    await startMicMeter();
    beginRecognition();
  }

  function closeLive() {
    if (!live.on) return;
    live.on = false;
    clearTimeout(live.timer);
    try { live.rec && live.rec.stop(); } catch { /* already stopped */ }
    live.rec = null;
    window.speechSynthesis.cancel();
    live.speaking = false;
    live.busy = false;
    stopMicMeter();
    if (orbRAF) cancelAnimationFrame(orbRAF);
    orbRAF = null;
    liveOverlay.hidden = true;
    document.body.classList.remove("live-open");
    setLiveState("Listening", "listening");
  }

  $("#liveClose").addEventListener("click", closeLive);
  $("#liveEnd").addEventListener("click", closeLive);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && live.on) closeLive();
  });

  liveMute.addEventListener("click", () => {
    live.muted = !live.muted;
    liveMute.classList.toggle("on", live.muted);
    if (live.muted) {
      clearTimeout(live.timer);
      window.speechSynthesis.cancel();
      live.speaking = false;
      try { live.rec && live.rec.stop(); } catch { /* already stopped */ }
      live.rec = null;
      setLiveState("Muted", "muted");
    } else {
      setLiveState("Listening", "listening");
      beginRecognition();
    }
  });

  micBtn.addEventListener("click", openLive);

  // Whether replies are read aloud. Applies to live mode and to text chat.
  function applySpeakState() {
    speakBtn.classList.toggle("on", speakReplies);
    speakBtn.classList.toggle("off", !speakReplies);
    localStorage.setItem("charvis.speak", speakReplies ? "1" : "0");
    if (!live.on) toast(speakReplies ? "I will speak my replies" : "Replies will be text only");
  }
  speakBtn.addEventListener("click", () => {
    speakReplies = !speakReplies;
    applySpeakState();
  });
  applySpeakState();

  /* ── panels ───────────────────────────────────────────── */
  $$(".rail-btn").forEach((btn) =>
    btn.addEventListener("click", () => showPanel(btn.dataset.panel)));

  /* ── status polling ───────────────────────────────────── */
  function statBox(k, v, sub, cls) {
    return `<div class="stat"><div class="k">${esc(k)}</div>
      <div class="v ${cls || ""}">${esc(v)}</div>
      ${sub ? `<div class="s">${esc(sub)}</div>` : ""}</div>`;
  }

  let statusBusy = false;
  async function loadStatus() {
    if (statusBusy) return;
    statusBusy = true;
    try {
      const data = await api("/api/status");
      $("#linkDot").classList.add("online");
      const a = data.agent, m = data.memory, s = data.security;
      $("#version").textContent = "v" + (a.version || "—");

      $("#stats").innerHTML = [
        `<span>state <b>${esc(a.state)}</b></span>`,
        `<span>memory <b>${m.active_memories ?? 0}</b></span>`,
        `<span>lessons <b>${m.counts?.lessons ?? 0}</b></span>`,
        `<span>tools <b>${data.tools}</b></span>`,
        `<span>model <b>${esc(a.model?.provider || "offline")}</b></span>`,
        `<span>posture <b>${esc(s.posture)}</b></span>`,
      ].join("");

      const select = $("#ownerName");
      if (select.options.length <= 1) {
        select.innerHTML = '<option value="">name…</option>';
      }
    } catch (err) {
      $("#linkDot").classList.remove("online");
    } finally {
      statusBusy = false;
    }
  }

  /* ── brain panel ──────────────────────────────────────── */
  async function loadBrain() {
    try {
      const data = await api("/api/memory");
      const m = data.stats;
      $("#memStats").innerHTML = [
        statBox("active", m.active_memories ?? 0, "memories", "good"),
        statBox("episodes", m.episodes?.total ?? 0,
                `${Math.round((m.episodes?.success_rate ?? 0) * 100)}% success`),
        statBox("lessons", m.counts?.lessons ?? 0, "rules learned"),
        statBox("size", ((m.db_bytes ?? 0) / 1024).toFixed(0) + " KB", "on disk"),
        statBox("vectors", m.vector_dim ?? 0, m.fts ? "FTS5 index" : "LIKE index"),
      ].join("");

      const lessons = await api("/api/nlu");
      $("#lessonList").innerHTML =
        `<div class="chip">${lessons.total_parsed ?? 0} requests parsed ·
          ${lessons.known_intents ?? 0} intents known</div>`;

      const rules = await post("/api/tool", { name: "lesson.list" }).catch(() => null);
      if (rules?.output?.lessons?.length) {
        $("#lessonList").innerHTML = rules.output.lessons
          .slice(0, 10)
          .map((l) => `<div class="chip"><b>${Math.round(l.confidence * 100)}%</b> ${esc(l.rule)}</div>`)
          .join("");
      }

      await loadMind();
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function loadMind() {
    try {
      const m = await api("/api/mind");
      $("#mindStats").innerHTML = [
        statBox("trained on", m.trained_examples ?? 0, "examples of your requests", "good"),
        statBox("intents", m.classes ?? 0, "recognised"),
        statBox("weights", (m.weights_stored ?? 0).toLocaleString(),
                "learned connections"),
        statBox("corrections", m.corrections_learned ?? 0, "you corrected me"),
      ].join("");

      const weak = m.calibration || [];
      const learned = m.best_learned || [];
      const parts = [];
      if (learned.length) {
        parts.push(`<div class="result"><div><b>strongest</b></div><div class="meta">${
          learned.slice(0, 5).map((r) => `${esc(r.intent)} ${r.learned_weight.toFixed(1)}`).join(" · ")
        }</div></div>`);
      }
      if (weak.length) {
        parts.push(`<div class="result warn"><div><b>still weak at</b> (so I stay careful there)</div>
          <div class="meta">${weak.slice(0, 4).map(
            (r) => `${esc(r.intent)} ${Math.round(r.success_rate * 100)}%`).join(" · ")}</div></div>`);
      }
      const bandit = m.bandit || {};
      if (bandit.best?.length) {
        parts.push(`<div class="result"><div><b>actions that work</b></div><div class="meta">${
          bandit.best.slice(0, 4).map((r) => `${esc(r.arm)} ${Math.round(r.success_rate * 100)}%`).join(" · ")
        }</div></div>`);
      }
      $("#mindProbeOut").innerHTML = parts.join("") ||
        `<div class="result">not trained yet — just keep talking to me and this fills up</div>`;
    } catch (err) { /* non fatal */ }
  }

  let probeTimer = null;
  $("#mindProbe").addEventListener("input", (e) => {
    clearTimeout(probeTimer);
    const q = e.target.value.trim();
    if (q.length < 3) return;
    probeTimer = setTimeout(async () => {
      try {
        const r = await post("/api/mind", { action: "explain", text: q });
        const rows = (r.ranked || []).slice(0, 5);
        $("#mindProbeOut").innerHTML = rows.map((x) => {
          const bar = "#".repeat(Math.max(1, Math.round(x.probability * 34)));
          return `<div class="result"><div>${esc(x.intent)}
            <b>${(x.probability * 100).toFixed(1)}%</b></div>
            <div class="meta">${esc(bar)}</div></div>`;
        }).join("") || `<div class="result">no signal yet</div>`;
      } catch (err) { /* ignore keystroke races */ }
    }, 260);
  });

  $("#mindReset").addEventListener("click", async () => {
    if (!confirm("Reset the mind? Everything it has learned will be forgotten.")) return;
    try {
      await post("/api/mind", { action: "reset" });
      toast("mind reset — learning from scratch again");
      loadMind();
    } catch (err) { toast(err.message, true); }
  });

  $("#memQuery").addEventListener("input", async (e) => {
    const q = e.target.value.trim();
    const box = $("#memResults");
    if (!q) { box.innerHTML = ""; return; }
    try {
      const data = await api("/api/memory?q=" + encodeURIComponent(q));
      box.innerHTML = data.results.length
        ? data.results.map((r) => `
            <div class="result">
              <div>${esc(r.text)}</div>
              <div class="meta">${esc(r.kind)} · relevance ${(r.score * 100).toFixed(0)}% ·
                importance ${r.importance} · ${esc((r.tags || []).join(", ") || "no tags")}</div>
            </div>`).join("")
        : `<div class="result">nothing stored about that yet</div>`;
    } catch (err) { /* ignore keystroke races */ }
  });

  $("#improveBtn").addEventListener("click", async () => {
    const btn = $("#improveBtn");
    btn.disabled = true;
    $("#improveOut").textContent = "running…";
    try {
      const data = await post("/api/improve", { full: true });
      $("#improveOut").textContent = JSON.stringify(data.report, null, 2);
      toast("Improvement cycle finished");
      loadBrain();
    } catch (err) {
      $("#improveOut").textContent = "failed: " + err.message;
      toast(err.message, true);
    } finally { btn.disabled = false; }
  });

  /* ── shield panel ─────────────────────────────────────── */
  async function loadShield() {
    try {
      const s = await api("/api/security");
      const d = s.decisions || {};
      $("#secStats").innerHTML = [
        statBox("posture", s.posture, `confirm above ${Math.round(s.risk_threshold * 100)}%`,
                s.posture === "paranoid" ? "warn" : "good"),
        statBox("allowed", d.allow ?? 0, "actions", "good"),
        statBox("confirmed", d.ask ?? 0, "asked first", "warn"),
        statBox("blocked", d.block ?? 0, "refused", (d.block ? "bad" : "")),
        statBox("audit", s.audit?.entries ?? 0,
                s.audit?.chain_intact ? "chain intact"
                  : `broken at line ${s.audit?.broken_at ?? "?"}`,
                s.audit?.chain_intact ? "good" : "bad"),
      ].join("");
      $("#postureNote").textContent = s.advice
        ? `My recommendation: ${s.advice.recommended_posture} — ${s.advice.why}`
        : "";
      $$("#postureRow button").forEach((b) =>
        b.classList.toggle("is-active", b.dataset.posture === s.posture));

      const v = await api("/api/vault");
      $("#vaultList").innerHTML = v.secrets.length
        ? v.secrets.map((x) => `<div class="chip"><b>${esc(x.key)}</b>
             <span class="meta">${esc(x.note || "")} ${esc(x.set_at || "")}</span></div>`).join("")
        : `<div class="chip">vault is empty</div>`;

      const ev = await api("/api/events");
      $("#auditList").innerHTML = ev.events.slice(-14).reverse().map((e) => `
        <div class="result">
          <div>${esc(e.name)}</div>
          <div class="meta">${esc(e.source)} · ${e.age.toFixed(1)}s ago</div>
        </div>`).join("") || `<div class="result">no activity yet</div>`;
    } catch (err) { toast(err.message, true); }
  }

  $$("#postureRow button").forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        await post("/api/posture", { posture: btn.dataset.posture });
        toast(`posture → ${btn.dataset.posture}`);
        loadShield();
      } catch (err) { toast(err.message, true); }
    }));

  $("#secSave").addEventListener("click", async () => {
    const key = $("#secKey").value.trim(), value = $("#secVal").value;
    if (!key || !value) { toast("key and value both needed", true); return; }
    try {
      await post("/api/secret", { key, value });
      $("#secKey").value = $("#secVal").value = "";
      toast(`'${key}' encrypted into the vault`);
      loadShield();
    } catch (err) { toast(err.message, true); }
  });

  /* ── studio panel ─────────────────────────────────────── */
  let styles = [], galleryLoaded = false;

  async function loadStudio() {
    if (styles.length) return;
    try {
      const list = await post("/api/tool", { name: "media.styles" });
      styles = list.output || [];
      // "ai" is the real diffusion model and must be the default - the
      // procedural styles are the offline fallback, not the main path.
      const chips = ["ai", ...styles];
      $("#styleRow").innerHTML = chips
        .map((s, i) => `<button data-style="${esc(s)}" class="${i === 0 ? "is-active" : ""}">${
          esc(s === "ai" ? "AI (real)" : s)}</button>`)
        .join("");
      $$("#styleRow button").forEach((b) =>
        b.addEventListener("click", () => {
          $$("#styleRow button").forEach((x) => x.classList.remove("is-active"));
          b.classList.add("is-active");
        }));
    } catch (err) { toast(err.message, true); }
    if (!galleryLoaded) { galleryLoaded = true; loadGallery(); }
  }

  const chosenStyle = () => {
    const chip = $("#styleRow .is-active")?.dataset.style;
    return chip === "ai" ? "auto" : (chip || "auto");
  };

  async function afterArt(path, label) {
    await loadGallery();
    const img = $(`#gallery figure[data-path="${CSS.escape(path)}"]`);
    if (img) img.scrollIntoView({ behavior: "smooth", block: "center" });
    toast(label + " saved");
  }

  $("#imgBtn").addEventListener("click", async () => {
    const prompt = $("#artPrompt").value.trim() || "open charvis";
    const btn = $("#imgBtn"); btn.disabled = true;
    toast("generating…");
    try {
      const r = await post("/api/image", { prompt, style: chosenStyle(), width: 448, height: 448 });
      if (r.warning) toast(r.warning, true);
      await loadGallery();
      // put the newest render at the front so it is the first thing seen
      const fig = $("#gallery figure");
      if (fig) fig.scrollIntoView({ behavior: "smooth", block: "center" });
      toast(r.engine ? `done - ${r.engine}` : "done");
    } catch (err) { toast(err.message, true); }
    finally { btn.disabled = false; }
  });

  $("#animBtn").addEventListener("click", async () => {
    const prompt = $("#artPrompt").value.trim() || "open charvis";
    const btn = $("#animBtn"); btn.disabled = true;
    toast("rendering frames…");
    try {
      const r = await post("/api/tool", {
        name: "media.animation",
        args: { prompt, style: chosenStyle(), frames: 18, size: 224, fps: 12 },
      });
      if (r.output?.animated_svg) {
        $("#gallery").insertAdjacentHTML("afterbegin", mediaCard(r.output.animated_svg, "svg", "animation"));
      }
      toast("animation rendered");
    } catch (err) { toast(err.message, true); }
    finally { btn.disabled = false; }
  });

  function mediaCard(path, kind, name) {
    const src = "/api/media?path=" + encodeURIComponent(path);
    return `<figure data-path="${esc(path)}">
      <img src="${esc(src)}" alt="${esc(name)}" loading="lazy" />
      <figcaption>${esc(name)} · ${esc(kind)}</figcaption></figure>`;
  }

  async function loadGallery() {
    try {
      const r = await post("/api/tool", { name: "media.gallery" });
      const items = r.output || [];
      $("#gallery").innerHTML = items.length
        ? items.map((i) => mediaCard(i.path, i.type, i.name)).join("")
        : `<div class="hint">nothing generated yet — describe something above</div>`;
    } catch (err) { /* non fatal */ }
  }
  $("#galleryBtn").addEventListener("click", loadGallery);

  /* ── lab panel ────────────────────────────────────────── */
  let language = "python";
  let labLoaded = false;

  async function loadLab() {
    if (!labLoaded) {
      labLoaded = true;
      try {
        const r = await post("/api/tool", { name: "dev.languages" });
        const ready = (r.output || []).filter((l) => l.ready);
        $("#langRow").innerHTML = ready.map((l) =>
          `<button data-lang="${esc(l.language)}"
             class="${l.language === "python" ? "is-active" : ""}">${esc(l.language)}</button>`).join("");
        $$("#langRow button").forEach((b) =>
          b.addEventListener("click", () => {
            $$("#langRow button").forEach((x) => x.classList.remove("is-active"));
            b.classList.add("is-active");
            language = b.dataset.lang;
          }));
      } catch (err) { toast(err.message, true); }
      try {
        const t = await api("/api/tools");
        $("#toolList").innerHTML = (t.tools || []).map((x) => `
          <div class="result">
            <div><b>${esc(x.name)}</b> <span class="meta">risk ${x.risk}</span></div>
            <div class="meta">${esc(x.description)}</div>
          </div>`).join("");
      } catch (err) { /* non fatal */ }
    }
    if (!$("#codeOut").textContent) {
      $("#codeOut").textContent = "pick a language, write code, press Run.";
    }
  }

  $("#runBtn").addEventListener("click", async () => {
    const btn = $("#runBtn"); btn.disabled = true;
    $("#codeOut").textContent = "running…";
    try {
      const r = await post("/api/tool", {
        name: "dev.run",
        args: {
          code: $("#code").value,
          language,
          stdin: $("#stdin").value,
        },
      });
      const o = r.output || {};
      $("#codeOut").textContent =
        (o.error ? "ERROR: " + o.error + "\n\n" : "") +
        (o.stdout || "(no stdout)") +
        (o.stderr ? "\n\n--- stderr ---\n" + o.stderr : "") +
        (o.duration_s !== undefined ? `\n\nexit ${o.exit_code} in ${o.duration_s}s` : "");
    } catch (err) {
      $("#codeOut").textContent = "failed: " + err.message;
    } finally { btn.disabled = false; }
  });

  $("#testBtn").addEventListener("click", async () => {
    const btn = $("#testBtn"); btn.disabled = true;
    $("#codeOut").textContent = "running the agent's own test suite…";
    try {
      const r = await post("/api/tool", { name: "dev.test" });
      const o = r.output || {};
      $("#codeOut").textContent =
        `${o.summary || o.error || ""}\n\n${o.output || ""}`.trim() || "no output";
    } catch (err) {
      $("#codeOut").textContent = "failed: " + err.message;
    } finally { btn.disabled = false; }
  });

  /* ── history ──────────────────────────────────────────── */
  async function loadHistory() {
    try {
      const data = await api("/api/history");
      const box = $("#histList");
      if (!data.sessions.length) {
        box.innerHTML = `<div class="hint">No conversations yet. They appear here
          automatically as you talk, and survive a restart.</div>`;
        return;
      }
      box.innerHTML = data.sessions.map((s) => `
        <div class="hist-item">
          <div>
            <b>${esc(s.title || 'Untitled')}</b>
            <div class="meta">${s.messages} messages · updated ${esc(s.updated)}</div>
          </div>
          <div class="hist-actions">
            <button data-open="${esc(s.id)}">Open</button>
            <button data-del="${esc(s.id)}">Delete</button>
          </div>
        </div>`).join("");

      $$("#histList [data-open]").forEach((b) =>
        b.addEventListener("click", () => openSession(b.dataset.open)));
      $$("#histList [data-del]").forEach((b) =>
        b.addEventListener("click", async () => {
          await post("/api/history", { action: "clear", session: b.dataset.del });
          loadHistory();
          toast("conversation deleted");
        }));
    } catch (err) { toast(err.message, true); }
  }

  async function openSession(id) {
    try {
      const data = await api("/api/history?session=" + encodeURIComponent(id));
      currentSession = id;
      log.innerHTML = "";
      data.messages.forEach((m) =>
        bubble(m.role === "user" ? "user" : "bot", m.text,
               m.intent ? { intent: m.intent } : {}));
      $$(".rail-btn").forEach((b) => b.classList.remove("is-active"));
      $('.rail-btn[data-panel="talk"]').classList.add("is-active");
      $$(".panel").forEach((p) => p.classList.toggle("is-active", p.dataset.panel === "talk"));
      scrollDown();
      toast(`opened "${id}"`);
    } catch (err) { toast(err.message, true); }
  }

  $("#histClear").addEventListener("click", async () => {
    if (!confirm("Delete every saved conversation?")) return;
    await post("/api/history", { action: "clear" });
    loadHistory();
    toast("history cleared");
  });
  $("#histExport").addEventListener("click", async () => {
    const r = await post("/api/history", { action: "export" });
    toast("exported to " + r.path.split("\\").pop());
  });

  // History was a small icon on the rail and easy to miss even though it
  // is one of the most-used panels. It now also sits in the top bar with a
  // count on it, so the number of past conversations is always visible.
  function showPanel(name) {
    $$(".rail-btn").forEach((b) => b.classList.remove("is-active"));
    const btn = $(`.rail-btn[data-panel="${name}"]`);
    if (btn) btn.classList.add("is-active");
    $$(".panel").forEach((p) => p.classList.toggle("is-active", p.dataset.panel === name));
    if (name === "brain")    loadBrain();
    if (name === "shield")   loadShield();
    if (name === "studio")   loadStudio();
    if (name === "lab")      loadLab();
    if (name === "history")  loadHistory();
    if (name === "settings") loadSettings();
  }

  $("#historyBtn").addEventListener("click", () => {
    showPanel("history");
  });

  $("#newChatBtn").addEventListener("click", async () => {
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    live.heard = "";
    live.pending = "";
    // A fresh id rather than "default", otherwise every conversation in
    // the browser would pile up into one endless transcript.
    currentSession = "s" + Date.now().toString(36);
    log.innerHTML = "";
    liveSaid.textContent = "";
    liveReply.textContent = "";
    renderStarters();
    showPanel("talk");
    bubble("bot",
      "New conversation. Everything you said before is still in history — " +
      "open it from the history button if you want it back.");
    input.focus();
    toast("new conversation started");
    refreshHistoryBadge();
  });

  async function refreshHistoryBadge() {
    try {
      const data = await api("/api/history");
      const badge = $("#historyCount");
      const n = (data.sessions || []).length;
      badge.textContent = String(n);
      badge.hidden = n === 0;
    } catch { /* badge is decoration, never block on it */ }
  }

  /* ── settings ─────────────────────────────────────────── */
  const ACCENTS = ["cyan", "violet", "amber", "emerald", "rose"];
  let settingsCache = [];

  async function loadSettings() {
    try {
      const p = await api("/api/profile");
      $("#profName").value = p.profile.name || "";
      $("#profTitle").value = p.profile.title || "";
      $("#profStatus").textContent = p.profile.signed_in
        ? "Passphrase is set — it never leaves this machine."
        : "No passphrase. Anyone at this computer can use the agent.";
      $("#accentRow").innerHTML = ACCENTS.map((a) =>
        `<button data-accent="${a}" class="${a === p.profile.accent ? "is-active" : ""}">${a}</button>`
      ).join("");
      $$("#accentRow button").forEach((b) =>
        b.addEventListener("click", async () => {
          await post("/api/profile", { accent: b.dataset.accent });
          applyAccent(b.dataset.accent);
          loadSettings();
        }));

      const data = await api("/api/settings");
      settingsCache = data.settings;
      const groups = {};
      settingsCache.forEach((s) => { (groups[s.group_title] ||= []).push(s); });

      $("#settingsList").innerHTML = Object.entries(groups).map(([title, rows]) => `
        <div class="set-group">
          <h3>${esc(title)}</h3>
          ${rows.map((r) => settingRow(r)).join("")}
        </div>`).join("");

      $$("#settingsList [data-key]").forEach((el) =>
        el.addEventListener("change", () => saveSetting(el)));
    } catch (err) { toast(err.message, true); }
  }

  function settingRow(r) {
    const id = `set-${r.key}`;
    let control;
    if (r.kind === "bool") {
      control = `<label class="switch"><input type="checkbox" id="${id}" data-key="${esc(r.key)}"
        ${r.value ? "checked" : ""} /><span></span></label>`;
    } else if (r.kind === "int" || r.kind === "float") {
      control = `<input type="number" step="${r.kind === "float" ? "0.05" : "1"}"
        id="${id}" data-key="${esc(r.key)}" value="${esc(r.value)}" />`;
    } else if (r.kind === "list") {
      control = `<input type="text" id="${id}" data-key="${esc(r.key)}"
        value="${esc((r.value || []).join(", "))}" />`;
    } else if (r.kind === "posture") {
      control = `<select id="${id}" data-key="${esc(r.key)}">
        ${["paranoid", "balanced", "sandbox", "open"].map((o) =>
          `<option ${o === r.value ? "selected" : ""}>${o}</option>`).join("")}
      </select>`;
    } else {
      control = `<input type="text" id="${id}" data-key="${esc(r.key)}"
        value="${esc(r.value)}" />`;
    }
    return `<label class="set-row"><span>${esc(r.label)}</span>${control}</label>`;
  }

  async function saveSetting(el) {
    const key = el.dataset.key;
    let value = el.type === "checkbox" ? el.checked : el.value;
    try {
      const r = await post("/api/settings", { values: { [key]: value } });
      toast(`${key} → ${JSON.stringify(r.changed[key])}`);
      if (key === "posture") loadShield();
    } catch (err) {
      toast(err.message, true);
      loadSettings();
    }
  }

  $("#profSave").addEventListener("click", async () => {
    try {
      await post("/api/profile", {
        name: $("#profName").value.trim(),
        title: $("#profTitle").value.trim(),
      });
      toast("saved");
      loadStatus();
      loadSettings();
    } catch (err) { toast(err.message, true); }
  });

  $("#profSetPass").addEventListener("click", async () => {
    const pass = $("#profPass").value;
    if (!pass) return toast("type a passphrase first", true);
    const r = await post("/api/profile", { action: "setpass", passphrase: pass });
    if (r.ok) { toast("passphrase set"); $("#profPass").value = ""; }
    else toast(r.error || "failed", true);
    loadSettings();
  });

  $("#profRemovePass").addEventListener("click", async () => {
    await post("/api/profile", { action: "logout" });
    toast("passphrase removed");
    loadSettings();
  });

  $("#settingsSave").addEventListener("click", async () => {
    const values = {};
    $$("#settingsList [data-key]").forEach((el) => {
      values[el.dataset.key] = el.type === "checkbox" ? el.checked : el.value;
    });
    try {
      await post("/api/settings", { values, save: true });
      toast("settings saved to disk");
    } catch (err) { toast(err.message, true); }
  });

  $("#settingsReset").addEventListener("click", () => {
    loadSettings();
    toast("reloaded from the running agent");
  });

  function applyAccent(name) {
    const map = {
      cyan: ["#34e0ff", "#7b5cff"], violet: ["#b06cff", "#ff6cd6"],
      amber: ["#ffc857", "#ff7a3d"], emerald: ["#2ee6a8", "#34e0ff"],
      rose: ["#ff5d7a", "#ff9f6c"],
    };
    const pair = map[name] || map.cyan;
    document.documentElement.style.setProperty("--accent", pair[0]);
    document.documentElement.style.setProperty("--accent-2", pair[1]);
  }

  /* ── welcome screen ─────────────────────────────────────── */
  const welcome = $("#welcome");
  const QUICK = {
    "create an image or sticker": "draw an image of a ",
    "write and edit": "help me write ",
    "search the web for": "search the web for ",
    "review this code": "review this code for bugs and risks",
    "turn on think mode": null,
  };

  $$("#welcome .quick button").forEach((b) =>
    b.addEventListener("click", () => {
      const key = b.dataset.q;
      if (key === "turn on think mode") {
        setThink(true);
        toast("Think is on — I will show my working");
        return;
      }
      const prefix = QUICK[key];
      if (prefix) {
        input.value = prefix;
        autosize();
        input.focus();
      } else {
        send(key);
      }
    }));

  function hideWelcome() {
    if (welcome && !welcome.hidden) welcome.hidden = true;
  }

  /* ── think mode ─────────────────────────────────────────── */
  let thinkOn = false;
  const thinkBtn = $("#thinkBtn");

  function setThink(on) {
    thinkOn = on;
    thinkBtn.classList.toggle("on", on);
    localStorage.setItem("charvis.think", on ? "1" : "0");
    post("/api/chat/think", { enabled: on }).catch(() => {});
  }
  thinkBtn.addEventListener("click", () => {
    setThink(!thinkOn);
    toast(thinkOn ? "Think on — you will see my working" : "Think off");
  });
  if (localStorage.getItem("charvis.think") === "1") setThink(true);

  /* ── attachments ────────────────────────────────────────── */
  const attachments = [];

  $("#attachBtn").addEventListener("click", () => $("#fileInput").click());
  $("#fileInput").addEventListener("change", async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
    for (const file of files) {
      const item = { name: file.name, size: file.size, path: "", state: "uploading" };
      attachments.push(item);
      renderAttachments();
      try {
        // The bytes go to the server now, so the answer is built from the
        // real file rather than from a filename we cannot open.
        const res = await fetch("/api/upload", {
          method: "POST",
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Filename": encodeURIComponent(file.name),
          },
          body: file,
        });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || "upload failed");
        item.path = data.path;
        item.name = data.name;
        item.state = "ready";
      } catch (err) {
        item.state = "failed";
        item.error = String(err.message || err);
      }
      renderAttachments();
    }
  });

  function renderAttachments() {
    $("#attachList").innerHTML = attachments.map((a, i) => {
      const mark = a.state === "ready" ? "ok"
        : a.state === "failed" ? "bad" : "wait";
      const label = a.state === "uploading" ? "uploading…"
        : a.state === "failed" ? (a.error || "failed") : "";
      return `
      <div class="att-chip" data-state="${mark}" title="${esc(a.name)}">
        <span class="n">${esc(a.name)} · ${Math.max(1, Math.round(a.size / 1024))}KB</span>
        ${label ? `<span class="s">${esc(label)}</span>` : ""}
        <button data-rm="${i}">×</button>
      </div>`;
    }).join("");
    $$("#attachList [data-rm]").forEach((b) =>
      b.addEventListener("click", () => {
        attachments.splice(Number(b.dataset.rm), 1);
        renderAttachments();
      }));
  }

  /* ── theme ────────────────────────────────────────────── */
  const savedTheme = localStorage.getItem("charvis.theme");
  if (savedTheme === "light") document.documentElement.dataset.theme = "light";
  $("#themeToggle").addEventListener("click", () => {
    const root = document.documentElement;
    const next = root.dataset.theme === "light" ? "dark" : "light";
    root.dataset.theme = next;
    localStorage.setItem("charvis.theme", next);
    toast(next + " theme");
  });

  // Apply the saved accent and load the profile without blocking boot.
  api("/api/profile")
    .then((p) => {
      applyAccent(p.profile.accent);
      $("#ownerName").value = p.profile.name || p.profile.title || "";
      document.title = p.profile.name ? `${p.profile.name} · Open Charvis` : "Open Charvis";
    })
    .catch(() => { applyAccent("cyan"); });

  /* ── boot ─────────────────────────────────────────────── */
  const BOOT_LINES = [
    "initialising core…",
    "loading memory store…",
    "arming security gates…",
    "registering tools…",
    "calibrating holographic core…",
    "ready",
  ];

  (async function boot() {
    const sub = $("#bootSub");
    for (let i = 0; i < BOOT_LINES.length; i++) {
      sub.textContent = BOOT_LINES[i];
      await new Promise((r) => setTimeout(r, 190));
      if (i === 1) loadStatus();
    }
    $("#boot").classList.add("done");
    $("#shell").hidden = false;

    renderStarters();
    autosize();
    loadStatus();
    refreshHistoryBadge();
    setInterval(loadStatus, 4000);

    bubble("bot",
      "I am awake.\n\n" +
      "Everything runs on this machine only. I remember what you tell me, learn rules from " +
      "my own mistakes, control your computer, search the internet, run code and create " +
      "images and animation.\n\n" +
      "Type below, tap the mic for a live conversation, or attach a file. " +
      "Say ‘exit’ and I will power down.");

    input.focus();
  })();
})();