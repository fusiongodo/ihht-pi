<script>
  import { defaultParams, locate, methods, searchOverlay, streamPresets } from "$lib/detect.js";

  const WIDTH = 2592;
  const HEIGHT = 1944;
  const labels = ["top-left", "top-right", "bottom-right", "bottom-left"];

  let saved = $state("");
  let error = $state("");
  let busy = $state(false);
  let score = $state(null);
  let corners = $state([]);
  let dragging = $state(null);
  let overlay = $state(null);
  let view = $state(null);
  let bboxNote = $state("");
  let scaleDraft = $state("");
  let ball = $state(null);
  let method = $state("glint");
  let params = $state(defaultParams());
  let preset = $state("1296");
  let frameSize = $state("");
  let switching = $state(false);
  let show = $state({ strip: true, bore: true, disk: true, glint: true });
  let hydrated = false;
  let loupe = $state(null);
  let recordKind = $state("steady");
  let recordFrames = $state(10);
  let recordScale = $state("");
  let recordNote = $state("");
  let recording = $state(false);
  const live = { method, params, corners, show };

  let hint = $derived(
    corners.length < 4 ? `Click ${labels[corners.length]}` : "Drag a corner, then save",
  );
  let polygon = $derived(corners.map((point) => point.join(",")).join(" "));
  let fields = $derived(methods[method].fields);
  const boreKeys = ["bore0", "bore1", "boreAngle"];
  let guides = $derived.by(() => {
    if (!show.bore || corners.length !== 4) return null;
    const current = params[method];
    return searchOverlay(corners, current.bore0, current.bore1, current.boreAngle || 0);
  });
  let kernel = $derived.by(() => {
    const current = params[method];
    if (!ball || current.glint == null || current.disk == null) return null;
    return { x: ball.peakX, y: ball.peakY, glint: current.glint, disk: current.disk };
  });

  $effect(() => {
    const visible = { strip: show.strip, bore: show.bore, disk: show.disk, glint: show.glint };
    live.method = method;
    live.params = params;
    live.corners = corners;
    live.show = show;
    if (!hydrated) {
      hydrated = true;
      const stored = loadSettings();
      method = stored.method;
      params = stored.params;
      show = stored.show;
      return;
    }
    localStorage.setItem("ihht-detect", JSON.stringify({ method, params, show: visible }));
  });

  $effect(() => {
    let stop = false;
    async function poll() {
      while (!stop) {
        try {
          const res = await fetch("/focus");
          const data = await res.json();
          score = data.score;
        } catch {
          score = null;
        }
        await new Promise((resolve) => setTimeout(resolve, 400));
      }
    }
    poll();
    return () => {
      stop = true;
    };
  });

  $effect(() => {
    let stop = false;
    fetch("/bbox")
      .then((res) => res.json())
      .then((data) => {
        if (!stop && Array.isArray(data.corners)) corners = data.corners;
      })
      .catch(() => {});
    fetch("/video")
      .then((res) => res.json())
      .then((data) => {
        if (!stop && data.preset) preset = data.preset;
      })
      .catch(() => {});
    return () => {
      stop = true;
    };
  });

  $effect(() => {
    const canvas = view;
    if (!canvas) return;
    let stop = false;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    async function frames() {
      while (!stop) {
        try {
          const res = await fetch("/frame", { cache: "no-store" });
          if (!res.ok) throw new Error("frame");
          const bitmap = await createImageBitmap(await res.blob());
          if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
            canvas.width = bitmap.width;
            canvas.height = bitmap.height;
          }
          const width = bitmap.width;
          const height = bitmap.height;
          context.drawImage(bitmap, 0, 0);
          const pixels = context.getImageData(0, 0, width, height);
          bitmap.close();
          frameSize = `${width}×${height}`;
          const gray = luma(pixels.data, width * height);
          const found =
            live.corners.length === 4
              ? locate(gray, width, height, live.corners, live.method, live.params[live.method])
              : null;
          ball = found;
          paintLoupe(loupe, canvas, width, height, found, live.params[live.method], live.show);
        } catch {
          await new Promise((resolve) => setTimeout(resolve, 300));
        }
      }
    }
    frames();
    return () => {
      stop = true;
    };
  });

  function paintLoupe(target, source, frameW, frameH, found, current, visible) {
    if (!target || !found || !visible || !current) return;
    if (!visible.strip && !visible.disk && !visible.glint) return;
    const zoom = 1.8;
    const span = 120;
    const size = Math.round(span * zoom);
    if (target.width !== size) {
      target.width = size;
      target.height = size;
    }
    const ctx = target.getContext("2d");
    const sx = (found.peakX - span / 2) * (frameW / WIDTH);
    const sy = (found.peakY - span / 2) * (frameH / HEIGHT);
    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(source, sx, sy, span * (frameW / WIDTH), span * (frameH / HEIGHT), 0, 0, size, size);
    const cx = size / 2;
    const cy = size / 2;
    if (visible.strip && current.strip) {
      const row = HEIGHT / current.strip;
      const pitch = row * zoom;
      const y0 = found.peakY - span / 2;
      ctx.beginPath();
      ctx.strokeStyle = "rgba(255, 204, 102, 0.92)";
      ctx.lineWidth = Math.max(1, Math.min(4, pitch * 0.28));
      for (let y = Math.ceil(y0 / row) * row; y < found.peakY + span / 2; y += row) {
        const ly = (y - y0) * zoom;
        ctx.moveTo(0, ly);
        ctx.lineTo(size, ly);
      }
      ctx.stroke();
    }
    const ring = (radius, color) => {
      const r = Math.max(1.2, radius * zoom);
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.strokeStyle = "#111";
      ctx.lineWidth = 4;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.stroke();
    };
    if (visible.disk && current.disk != null) ring(current.disk, "#f6f");
    if (visible.glint && current.glint != null) ring(current.glint, "#fff");
  }

  function luma(data, count) {
    const gray = new Float32Array(count);
    for (let i = 0, p = 0; p < count; i += 4, p += 1) {
      gray[p] = data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114;
    }
    return gray;
  }

  function loadSettings() {
    const params = defaultParams();
    try {
      const saved = JSON.parse(localStorage.getItem("ihht-detect") || "null");
      if (saved?.params) {
        for (const name of Object.keys(params)) {
          params[name] = { ...params[name], ...saved.params[name] };
        }
      }
      const show = { strip: true, bore: true, disk: true, glint: true };
      if (saved?.show) {
        for (const key of Object.keys(show)) {
          if (typeof saved.show[key] === "boolean") show[key] = saved.show[key];
        }
      }
      return { method: methods[saved?.method] ? saved.method : "glint", params, show };
    } catch {
      return { method: "glint", params, show: { strip: true, bore: true, disk: true, glint: true } };
    }
  }

  function toggleLayer(key) {
    show[key] = !show[key];
  }

  function pointFrom(event) {
    const box = overlay.getBoundingClientRect();
    const x = Math.round(((event.clientX - box.left) / box.width) * WIDTH);
    const y = Math.round(((event.clientY - box.top) / box.height) * HEIGHT);
    return [Math.min(WIDTH, Math.max(0, x)), Math.min(HEIGHT, Math.max(0, y))];
  }

  function addCorner(event) {
    if (corners.length >= 4 || dragging !== null) return;
    corners = [...corners, pointFrom(event)];
  }

  function startDrag(event, index) {
    event.stopPropagation();
    event.preventDefault();
    if (corners.length < 4 || dragging !== null) return;
    dragging = index;
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      overlay.setPointerCapture(event.pointerId);
    }
  }

  function moveDrag(event) {
    if (dragging === null) return;
    const index = dragging;
    corners = corners.map((point, i) => (i === index ? pointFrom(event) : point));
  }

  function endDrag() {
    dragging = null;
  }

  function clearCorners() {
    corners = [];
    bboxNote = "";
  }

  function setField(key, value) {
    params = { ...params, [method]: { ...params[method], [key]: Number(value) } };
  }

  async function choosePreset(id) {
    switching = true;
    error = "";
    try {
      const res = await fetch("/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ preset: id }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      preset = data.preset;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      switching = false;
    }
  }

  async function saveCorners() {
    error = "";
    bboxNote = "";
    try {
      const res = await fetch("/bbox", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ width: WIDTH, height: HEIGHT, corners }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      corners = data.corners;
      bboxNote = "Saved bbox.json";
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  function chooseKind(kind) {
    recordKind = kind;
    recordFrames = kind === "steady" ? 10 : 300;
  }

  function parseScale(raw, required) {
    const text = String(raw ?? "").trim().replace(",", ".");
    if (text === "") {
      if (required) throw new Error("Scale is required for steady");
      return null;
    }
    if (!/^-?\d+(\.\d+)?$/.test(text)) throw new Error("Scale must be a number");
    return Number(text);
  }

  async function record() {
    if (recording) return;
    error = "";
    recordNote = "";
    let scale;
    try {
      scale = parseScale(recordScale, false);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      return;
    }
    const count = Number(recordFrames);
    if (!Number.isInteger(count) || count < 1 || count > 999) {
      error = "Frames must be an integer from 1 to 999";
      return;
    }
    recording = true;
    try {
      const res = await fetch("/record", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ frames: count, kind: recordKind, scale }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      const id = data.id;
      recordNote = `Recording 0/${data.frames}`;
      const deadline = Date.now() + 15 * 60 * 1000;
      while (true) {
        if (Date.now() > deadline) throw new Error("recording timed out");
        await new Promise((resolve) => setTimeout(resolve, 250));
        const statusRes = await fetch("/record", { cache: "no-store" });
        const status = await statusRes.json();
        if (!statusRes.ok) throw new Error(status.error || statusRes.statusText);
        if (status.active === id) {
          recordNote = `Recording ${status.done}/${status.total}`;
          continue;
        }
        if (status.last === id && status.done === status.total && !status.active) break;
        throw new Error(
          status.last === id ? `recording incomplete ${status.done}/${status.total}` : "recording failed",
        );
      }
      recordNote = `Saved ${id}`;
      if (recordKind === "steady") recordScale = "";
      const pulled = await fetch("/recordings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      const body = await pulled.json();
      if (!pulled.ok) throw new Error(body.error || pulled.statusText);
      recordNote = `Pulled ${id}`;
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      recording = false;
    }
  }

  async function snap() {
    const raw = scaleDraft == null ? "" : String(scaleDraft).trim().replace(",", ".");
    let scale = null;
    if (raw !== "") {
      if (!/^-?\d+(\.\d+)?$/.test(raw)) {
        error = "Scale must be a number";
        return;
      }
      scale = Number(raw);
    }
    busy = true;
    error = "";
    try {
      const res = await fetch("/snap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scale }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      saved = data.file;
      scaleDraft = "";
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
    }
  }
</script>

<main>
  <p class="nav"><a href="/main">Main</a> · <a href="/annotate">Annotate shots</a> · <a href="/label">Label recordings</a> · <a href="/play">Playback</a></p>
  <div class="workspace">
  <div class="feed">
  <div class="stage">
    <canvas bind:this={view}></canvas>
    <canvas bind:this={loupe} class="loupe" class:off={!show.strip && !show.disk && !show.glint}></canvas>
    <svg
      bind:this={overlay}
      viewBox="0 0 {WIDTH} {HEIGHT}"
      preserveAspectRatio="none"
      onclick={addCorner}
      onpointermove={moveDrag}
      onpointerup={endDrag}
    >
      {#if corners.length >= 2}
        <polygon
          points={polygon}
          fill="rgba(80, 180, 255, 0.28)"
          stroke="#8cf"
          stroke-width="2"
          vector-effect="non-scaling-stroke"
        />
      {/if}
      {#if guides}
        <path
          d={guides.lines}
          fill="none"
          stroke="#fc6"
          stroke-width="2"
          vector-effect="non-scaling-stroke"
          pointer-events="none"
        />
      {/if}
      {#if ball}
        <circle
          cx={ball.x}
          cy={ball.y}
          r="14"
          fill="#fc6"
          stroke="#111"
          stroke-width="2"
          vector-effect="non-scaling-stroke"
          pointer-events="none"
        />
      {/if}
      {#if kernel && show.disk}
        <circle
          cx={kernel.x}
          cy={kernel.y}
          r={kernel.disk}
          fill="none"
          stroke="#111"
          stroke-width="5"
          vector-effect="non-scaling-stroke"
          pointer-events="none"
        />
        <circle
          cx={kernel.x}
          cy={kernel.y}
          r={kernel.disk}
          fill="none"
          stroke="#f6f"
          stroke-width="2"
          vector-effect="non-scaling-stroke"
          pointer-events="none"
        />
      {/if}
      {#if kernel && show.glint}
        <circle
          cx={kernel.x}
          cy={kernel.y}
          r={kernel.glint}
          fill="none"
          stroke="#111"
          stroke-width="5"
          vector-effect="non-scaling-stroke"
          pointer-events="none"
        />
        <circle
          cx={kernel.x}
          cy={kernel.y}
          r={kernel.glint}
          fill="none"
          stroke="#fff"
          stroke-width="2"
          vector-effect="non-scaling-stroke"
          pointer-events="none"
        />
      {/if}
      {#each corners as corner, index (index)}
        <circle
          role="button"
          aria-label={labels[index]}
          cx={corner[0]}
          cy={corner[1]}
          r="48"
          fill="#8cf"
          stroke="#111"
          stroke-width="2"
          vector-effect="non-scaling-stroke"
          onpointerdown={(event) => startDrag(event, index)}
          onclick={(event) => event.stopPropagation()}
        />
      {/each}
    </svg>
  </div>
  <p class="focus">Focus {score ?? "…"} — higher means the center is sharper</p>
  <p class="focus">
    {ball ? `Ball ${Math.round(ball.x)}, ${Math.round(ball.y)}` : "Ball …"}
    {frameSize ? ` · ${frameSize}` : ""}
  </p>
  <p class="hint">{hint}</p>
  <div class="actions">
    <label class="scale">
      Scale
      <input type="number" step="any" bind:value={scaleDraft} />
    </label>
    <button type="button" onclick={snap} disabled={busy}>
      {busy ? "Saving…" : "Take photo"}
    </button>
    <button type="button" onclick={clearCorners} disabled={corners.length === 0}>Clear</button>
    <button type="button" onclick={saveCorners} disabled={corners.length !== 4}>Save corners</button>
  </div>
  {#if saved}
    <p>Saved {saved}</p>
  {/if}
  {#if bboxNote}
    <p>{bboxNote}</p>
  {/if}
  {#if error}
    <p class="error">{error}</p>
  {/if}
  </div>
  <aside class="tuner">
    {#each fields.filter((field) => boreKeys.includes(field.key)) as field (field.key)}
      <label class="field">
        <span>{field.label}</span>
        <input
          type="range"
          min={field.min}
          max={field.max}
          step={field.step}
          value={params[method][field.key]}
          oninput={(event) => setField(field.key, event.currentTarget.value)}
        />
        <span class="value">{params[method][field.key]}</span>
      </label>
    {/each}
    <details class="tuning">
    <summary>Detector tuning</summary>
    <div class="presets">
      {#each streamPresets as item (item.id)}
        <button
          type="button"
          class:on={preset === item.id}
          disabled={switching || recording}
          onclick={() => choosePreset(item.id)}
        >
          {item.label}
        </button>
      {/each}
    </div>
    <label class="method">
      Method
      <select bind:value={method}>
        {#each Object.entries(methods) as [id, item] (id)}
          <option value={id}>{item.label}</option>
        {/each}
      </select>
    </label>
    <div class="layers">
      <button type="button" class:on={show.strip} onclick={() => toggleLayer("strip")}>Strip</button>
      <button type="button" class:on={show.bore} onclick={() => toggleLayer("bore")}>Bore</button>
      <button type="button" class:on={show.disk} onclick={() => toggleLayer("disk")}>Disk</button>
      <button type="button" class:on={show.glint} onclick={() => toggleLayer("glint")}>Glint</button>
    </div>
    {#each fields.filter((field) => !boreKeys.includes(field.key)) as field (field.key)}
      <label class="field">
        <span>{field.label}</span>
        <input
          type="range"
          min={field.min}
          max={field.max}
          step={field.step}
          value={params[method][field.key]}
          oninput={(event) => setField(field.key, event.currentTarget.value)}
        />
        <span class="value">{params[method][field.key]}</span>
      </label>
    {/each}
    </details>
    <div class="record">
      <p class="record-title">Record</p>
      <div class="kinds">
        <button type="button" class:on={recordKind === "steady"} onclick={() => chooseKind("steady")}>Steady</button>
        <button type="button" class:on={recordKind === "sweep"} onclick={() => chooseKind("sweep")}>Sweep</button>
      </div>
      <label class="scale">
        Frames
        <input type="number" min="1" max="999" step="1" bind:value={recordFrames} />
      </label>
      <label class="scale">
        Scale
        <input
          type="text"
          inputmode="decimal"
          spellcheck="false"
          bind:value={recordScale}
          placeholder="L/min"
        />
      </label>
      <button type="button" onclick={record} disabled={recording}>Record</button>
      {#if recordNote}
        <p class="focus">{recordNote}</p>
      {/if}
    </div>
  </aside>
  </div>
</main>

<style>
  :global(body) {
    margin: 0;
    background: #111;
    color: #eee;
    font-family: system-ui, sans-serif;
  }

  main {
    max-width: 1180px;
    margin: 0 auto;
    padding: 24px 16px 48px;
  }

  .workspace {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 22rem;
    gap: 20px;
    align-items: start;
  }

  a {
    color: #8cf;
  }

  .stage {
    position: relative;
    width: 100%;
    aspect-ratio: 4 / 3;
    background: #000;
  }

  canvas,
  svg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }

  canvas {
    display: block;
    object-fit: contain;
  }

  .loupe {
    position: absolute;
    inset: auto;
    left: 8px;
    bottom: 8px;
    z-index: 2;
    width: auto;
    height: auto;
    pointer-events: none;
    border: 2px solid #fc6;
    background: #000;
    image-rendering: pixelated;
  }

  .loupe.off {
    display: none;
  }

  svg {
    touch-action: none;
  }

  circle {
    cursor: grab;
  }

  .actions,
  .presets {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-top: 16px;
  }

  .presets {
    flex-direction: column;
    align-items: stretch;
  }

  .presets button {
    width: 100%;
  }

  .scale {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .method {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
    margin-top: 16px;
  }

  input[type="number"],
  input[type="text"],
  select {
    font: inherit;
    width: 8rem;
    padding: 8px 10px;
    border: 0;
    background: #eee;
    color: #111;
  }

  button {
    font: inherit;
    font-size: 1.05rem;
    padding: 12px 20px;
    border: 0;
    background: #eee;
    color: #111;
    cursor: pointer;
  }

  button.on {
    background: #fc6;
  }

  button:disabled {
    opacity: 0.5;
    cursor: default;
  }

  .tuner {
    position: sticky;
    top: 16px;
    max-height: calc(100vh - 32px);
    overflow: auto;
  }

  .method select {
    width: 100%;
  }

  .layers {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 16px;
  }

  .layers button {
    flex: 1;
    padding: 8px 10px;
  }

  .field {
    display: grid;
    grid-template-columns: 8.5rem 1fr 3.5rem;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
  }

  .field input {
    width: 100%;
  }

  .value {
    font-variant-numeric: tabular-nums;
    text-align: right;
  }

  .focus,
  .hint {
    margin: 12px 0 0;
    font-variant-numeric: tabular-nums;
  }

  .error {
    color: #f88;
  }

  .record {
    margin-top: 28px;
    padding-top: 16px;
    border-top: 1px solid #333;
  }

  .record-title {
    margin: 0;
    font-weight: 650;
  }

  .kinds {
    display: flex;
    gap: 8px;
    margin-top: 12px;
  }

  .kinds button {
    flex: 1;
  }

  .record .scale {
    margin-top: 12px;
  }

  .record > button {
    width: 100%;
    margin-top: 12px;
  }
</style>
