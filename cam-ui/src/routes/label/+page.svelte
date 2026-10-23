<script>
  import { defaultParams, locate } from "$lib/detect.js";

  const NATIVE_W = 2592;
  const NATIVE_H = 1944;
  const glintParams = defaultParams().glint;

  let clips = $state([]);
  let clipId = $state("");
  let labels = $state({});
  let corners = $state([]);
  let index = $state(0);
  let loaded = $state(false);
  let error = $state("");
  let zoomed = $state(false);
  let showMarks = $state(true);
  let showGuide = $state(true);
  let showLabel = $state(true);
  let showMag = $state(true);
  let markR = $state(40);
  let proposal = $state(null);
  let proposalFile = $state("");
  let mag = $state(null);
  let sheet = $state(null);
  let frameImg = $state(null);
  let magCanvas = $state(null);
  let viewport = $state(null);
  let viewW = $state(0);
  let viewH = $state(0);
  let detectGen = 0;
  let saveTail = Promise.resolve();

  let clip = $derived(clips.find((item) => item.id === clipId) ?? null);
  let file = $derived(clip?.frames?.[index]?.file ?? "");
  let current = $derived(labels[file] ?? null);
  let labeled = $derived(Object.keys(labels).length);
  let cropSize = $derived.by(() => {
    if (!clip?.crop) return { w: 1, h: 1 };
    const [x0, , x1, y1] = clip.crop;
    return { w: Math.max(1, x1 - x0), h: Math.max(1, y1) };
  });
  let shownProposal = $derived(proposal && proposalFile === file ? proposal : null);
  let previous = $derived.by(() => {
    if (!clip || index < 1) return null;
    const name = clip.frames[index - 1]?.file;
    const label = name ? labels[name] : null;
    if (!label || label.absent || !Number.isFinite(label.x)) return null;
    return label;
  });
  let anchor = $derived.by(() => {
    if (current && Number.isFinite(current.x)) return toCrop(current);
    if (shownProposal) return toCrop(shownProposal);
    if (previous) return toCrop(previous);
    return { x: cropSize.w / 2, y: cropSize.h / 2 };
  });
  let sheetW = $derived(zoomed ? viewW * 2 : viewW);
  let sheetH = $derived(zoomed ? viewH * 2 : viewH);
  let sheetX = $derived(zoomed ? viewW / 2 - (anchor.x / cropSize.w) * sheetW : 0);
  let sheetY = $derived(zoomed ? viewH / 2 - (anchor.y / cropSize.h) * sheetH : 0);
  let labelText = $derived.by(() => {
    if (!current) return "Unlabeled";
    if (current.absent) return "Absent";
    return `${current.x}, ${current.y} · ${current.source}`;
  });
  let proposalText = $derived.by(() => {
    if (proposalFile !== file) return "Proposal …";
    if (!shownProposal) return "No proposal";
    return `Proposal ${shownProposal.x}, ${shownProposal.y}`;
  });

  $effect(() => {
    let stop = false;
    Promise.all([fetch("/recordings").then((res) => res.json()), fetch("/bbox").then((res) => res.json())])
      .then(([data, box]) => {
        if (stop) return;
        clips = data.clips ?? [];
        corners = Array.isArray(box.corners) ? box.corners : [];
        if (!clipId && clips.length) clipId = clips[0].id;
        loaded = true;
      })
      .catch((err) => {
        if (stop) return;
        error = err instanceof Error ? err.message : String(err);
        loaded = true;
      });
    return () => {
      stop = true;
    };
  });

  $effect(() => {
    const id = clipId;
    if (!id) return;
    let stop = false;
    index = 0;
    labels = {};
    proposal = null;
    proposalFile = "";
    fetch(`/recordings/${id}`)
      .then((res) => res.json())
      .then((data) => {
        if (stop || clipId !== id) return;
        if (data.error) throw new Error(data.error);
        labels = { ...(data.labels?.frames ?? {}), ...labels };
        setLabeled(id, Object.keys(labels).length);
      })
      .catch((err) => {
        if (!stop) error = err instanceof Error ? err.message : String(err);
      });
    return () => {
      stop = true;
    };
  });

  $effect(() => {
    const el = viewport;
    if (!el) return;
    const measure = () => {
      viewW = el.clientWidth;
      viewH = el.clientHeight;
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  });

  $effect(() => {
    if (!showMag || !mag || !magCanvas || !frameImg) return;
    paintMag(mag.cropX, mag.cropY);
  });

  function setLabeled(id, count) {
    const item = clips.find((entry) => entry.id === id);
    if (item) item.labeled = count;
  }

  function clipLabel(item) {
    const scale = item.scale == null ? "" : ` · ${item.scale} L/min`;
    const count = item.frames?.length ?? 0;
    const labeled = item.labeled ?? 0;
    return `${item.id} · ${item.kind}${scale} · ${labeled}/${count}`;
  }

  function round2(value) {
    return Math.round(value * 100) / 100;
  }

  function toCrop(point) {
    if (!clip?.crop) return { x: 0, y: 0 };
    const [x0, y0] = clip.crop;
    return {
      x: point.x * (clip.frameWidth / NATIVE_W) - x0,
      y: point.y * (clip.frameHeight / NATIVE_H) - y0,
    };
  }

  function nativeFromCrop(cropX, cropY) {
    const [x0, y0] = clip.crop;
    const frameX = x0 + cropX;
    const frameY = y0 + cropY;
    return {
      x: round2(frameX * (NATIVE_W / clip.frameWidth)),
      y: round2(frameY * (NATIVE_H / clip.frameHeight)),
    };
  }

  function inside(point) {
    return point.x >= -8 && point.y >= -8 && point.x <= cropSize.w + 8 && point.y <= cropSize.h + 8;
  }

  function scan(img) {
    const name = file;
    const currentClip = clip;
    if (!img || !currentClip || corners.length !== 4 || !img.naturalWidth) return;
    const gen = ++detectGen;
    const [x0, y0, x1, y1] = currentClip.crop;
    const cropW = x1 - x0;
    const cropH = y1 - y0;
    const canvas = document.createElement("canvas");
    canvas.width = cropW;
    canvas.height = cropH;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(img, 0, 0, cropW, cropH);
    const pixels = context.getImageData(0, 0, cropW, cropH).data;
    const gray = new Float32Array(currentClip.frameWidth * currentClip.frameHeight);
    for (let y = 0; y < cropH; y += 1) {
      const row = (y + y0) * currentClip.frameWidth + x0;
      const src = y * cropW * 4;
      for (let x = 0; x < cropW; x += 1) gray[row + x] = pixels[src + x * 4];
    }
    let found = null;
    try {
      found = locate(gray, currentClip.frameWidth, currentClip.frameHeight, corners, "glint", glintParams);
    } catch {
      found = null;
    }
    if (gen !== detectGen || file !== name) return;
    proposal = found ? { x: round2(found.x), y: round2(found.y) } : null;
    proposalFile = name;
  }

  function onLoad(event) {
    scan(event.currentTarget);
  }

  function step(delta) {
    if (!clip?.frames?.length) return;
    index = Math.min(clip.frames.length - 1, Math.max(0, index + delta));
  }

  function enqueueSave(id, name, label) {
    saveTail = saveTail
      .then(async () => {
        let last = "save failed";
        for (let attempt = 0; attempt < 3; attempt += 1) {
          try {
            const res = await fetch(`/recordings/${id}`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ file: name, label }),
            });
            const data = await res.json();
            if (res.ok) return;
            last = data.error || res.statusText;
          } catch (err) {
            last = err instanceof Error ? err.message : String(err);
          }
          await new Promise((resolve) => setTimeout(resolve, 200));
        }
        throw new Error(last);
      })
      .catch((err) => {
        error = err instanceof Error ? err.message : String(err);
      });
  }

  function commit(name, label) {
    if (!clip) return;
    const next = { ...labels };
    if (label) next[name] = label;
    else delete next[name];
    labels = next;
    error = "";
    setLabeled(clip.id, Object.keys(next).length);
    enqueueSave(clip.id, name, label);
  }

  function place(event) {
    if (!clip || !file || !sheet) return;
    sheet.focus();
    const rect = sheet.getBoundingClientRect();
    const cropX = ((event.clientX - rect.left) / rect.width) * cropSize.w;
    const cropY = ((event.clientY - rect.top) / rect.height) * cropSize.h;
    if (cropX < 0 || cropY < 0 || cropX > cropSize.w || cropY > cropSize.h) return;
    const point = nativeFromCrop(cropX, cropY);
    commit(file, { ...point, source: "click" });
    step(1);
  }

  function accept() {
    if (!file || !shownProposal) return;
    commit(file, { x: shownProposal.x, y: shownProposal.y, source: "accepted" });
    step(1);
  }

  function markAbsent() {
    if (!file) return;
    commit(file, { absent: true });
    step(1);
  }

  function clearLabel() {
    if (!file || !labels[file]) return;
    commit(file, null);
  }

  function onKey(event) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const tag = event.target?.tagName;
    const stepKey = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key);
    if (tag === "SELECT" && stepKey) event.target.blur();
    else if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
    if (event.key === "g" || event.key === "G") {
      event.preventDefault();
      showGuide = !showGuide;
    } else if (event.key === "y" || event.key === "Y") {
      event.preventDefault();
      showLabel = !showLabel;
    } else if (event.key === "p" || event.key === "P") {
      event.preventDefault();
      showMag = !showMag;
    } else if (event.shiftKey && (event.key === "W" || event.key === "w")) {
      event.preventDefault();
      showMarks = !showMarks;
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      step(-1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      step(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      markR = Math.min(80, markR + 1);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      markR = Math.max(8, markR - 1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      accept();
    } else if (event.key === "a" || event.key === "A") {
      event.preventDefault();
      markAbsent();
    } else if (event.key === "Backspace") {
      event.preventDefault();
      clearLabel();
    }
  }

  function track(event) {
    if (!sheet || !frameImg) return;
    const rect = sheet.getBoundingClientRect();
    const cropX = ((event.clientX - rect.left) / rect.width) * cropSize.w;
    const cropY = ((event.clientY - rect.top) / rect.height) * cropSize.h;
    const box = 160;
    const ring = (markR * (clip.frameWidth / NATIVE_W) / cropSize.w) * rect.width;
    const gap = Math.round(ring + 28);
    let x = event.clientX + gap;
    let y = event.clientY + gap;
    if (x + box > window.innerWidth - 8) x = event.clientX - gap - box;
    if (y + box > window.innerHeight - 8) y = event.clientY - gap - box;
    mag = { x, y, cropX, cropY };
    if (showMag) paintMag(cropX, cropY);
  }

  function paintMag(cropX, cropY) {
    const canvas = magCanvas;
    const img = frameImg;
    if (!canvas || !img || !img.naturalWidth) return;
    const context = canvas.getContext("2d");
    const src = 160 / 8;
    const scaleX = img.naturalWidth / cropSize.w;
    const scaleY = img.naturalHeight / cropSize.h;
    context.imageSmoothingEnabled = false;
    context.fillStyle = "#000";
    context.fillRect(0, 0, 160, 160);
    context.drawImage(
      img,
      cropX * scaleX - (src * scaleX) / 2,
      cropY * scaleY - (src * scaleY) / 2,
      src * scaleX,
      src * scaleY,
      0,
      0,
      160,
      160,
    );
    context.strokeStyle = "#fc6";
    context.beginPath();
    context.moveTo(80, 0);
    context.lineTo(80, 160);
    context.moveTo(0, 80);
    context.lineTo(160, 80);
    context.stroke();
  }
</script>

<svelte:window onkeydown={onKey} />

<main>
  <p class="nav"><a href="/main">Main</a> · <a href="/">Camera</a> · <a href="/play">Playback</a></p>
  {#if !loaded}
    <p>Loading…</p>
  {:else if clips.length === 0}
    <p>No recordings yet.</p>
  {:else}
    <label class="picker">
      Clip
      <select bind:value={clipId} onchange={(event) => event.currentTarget.blur()}>
        {#each clips as item (item.id)}
          <option value={item.id}>{clipLabel(item)}</option>
        {/each}
      </select>
    </label>
    {#if clip && file}
      <div class="work">
        <div
          class="viewport"
          bind:this={viewport}
          style="aspect-ratio: {cropSize.w} / {cropSize.h}"
        >
          <div
            class="sheet"
            bind:this={sheet}
            tabindex="0"
            style={viewW
              ? `width:${sheetW}px;height:${sheetH}px;transform:translate(${sheetX}px,${sheetY}px)`
              : "width:100%;height:100%"}
            onclick={place}
            onpointermove={track}
            onpointerleave={() => (mag = null)}
          >
            {#key file}
              <img bind:this={frameImg} src={`/recordings/${clip.id}/${file}`} alt={file} draggable="false" onload={onLoad} />
            {/key}
            <svg viewBox="0 0 {cropSize.w} {cropSize.h}" preserveAspectRatio="none">
              {#if showMarks}
              {#if previous && inside(toCrop(previous))}
                {@const point = toCrop(previous)}
                <circle cx={point.x} cy={point.y} r="12" fill="rgba(255,255,255,0.16)" stroke="rgba(255,255,255,0.55)" stroke-width="2" vector-effect="non-scaling-stroke" />
              {/if}
              {#if shownProposal && inside(toCrop(shownProposal))}
                {@const point = toCrop(shownProposal)}
                <circle cx={point.x} cy={point.y} r="11" fill="none" stroke="#8cf" stroke-width="2" vector-effect="non-scaling-stroke" />
                <circle cx={point.x} cy={point.y} r="1.6" fill="#8cf" />
              {/if}
              {/if}
              {#if current && Number.isFinite(current.x) && inside(toCrop(current))}
                {@const point = toCrop(current)}
                {#if showGuide}
                  <circle cx={point.x} cy={point.y} r={markR * (clip.frameWidth / NATIVE_W)} fill="none" stroke="rgba(255, 204, 102, 0.35)" stroke-width="1" vector-effect="non-scaling-stroke" />
                {/if}
                {#if showLabel}
                  <circle cx={point.x} cy={point.y} r="8" fill="#fc6" stroke="#111" stroke-width="2" vector-effect="non-scaling-stroke" />
                {/if}
              {/if}
              {#if showGuide && mag && !current?.absent}
                <circle cx={mag.cropX} cy={mag.cropY} r={markR * (clip.frameWidth / NATIVE_W)} fill="none" stroke="rgba(255, 204, 102, 0.35)" stroke-width="1" vector-effect="non-scaling-stroke" />
              {/if}
            </svg>
          </div>
          <canvas
            bind:this={magCanvas}
            class="mag"
            class:off={!showMag || !mag}
            width="160"
            height="160"
            style={mag ? `left:${mag.x}px;top:${mag.y}px` : ""}
          ></canvas>
        </div>
        <aside>
          {#if clip.kind === "steady"}
            <p class="banner">{clip.scale ?? "—"} L/min</p>
          {/if}
          <p class="meta">{labeled} / {clip.frames.length} labeled</p>
          <label class="field">
            <span>Frame</span>
            <input
              type="range"
              min="0"
              max={clip.frames.length - 1}
              step="1"
              value={index}
              oninput={(event) => (index = Number(event.currentTarget.value))}
            />
            <span class="value">{index + 1}</span>
          </label>
          <p class="meta">{labelText}</p>
          <p class="meta">{proposalText}</p>
          <p class="steps">
            <button type="button" class:on={showLabel} onclick={() => (showLabel = !showLabel)}>Mark</button>
            <button type="button" class:on={showGuide} onclick={() => (showGuide = !showGuide)}>Guide</button>
            <button type="button" class:on={showMarks} onclick={() => (showMarks = !showMarks)}>Suggestions</button>
            <button type="button" class:on={showMag} onclick={() => (showMag = !showMag)}>Patch</button>
          </p>
          {#if showGuide}
            <label class="field">
              <span>Radius</span>
              <input
                type="range"
                min="8"
                max="80"
                step="1"
                value={markR}
                oninput={(event) => (markR = Number(event.currentTarget.value))}
              />
              <span class="value">{markR}</span>
            </label>
          {/if}
          <button type="button" class:on={zoomed} onclick={() => (zoomed = !zoomed)}>2×</button>
          <p class="steps">
            <button type="button" onclick={() => step(-1)}>◀ Back</button>
            <button type="button" onclick={() => step(1)}>Next ▶</button>
          </p>
          <p class="hint">Mark (Y) is your yellow click. Guide (G) is the hover ring. Patch (P) is the zoomed square. Suggestions (Shift+W) is the previous frame and the detector.</p>
          <p class="hint">Click labels and advances. Enter accepts the proposal. A marks absent. Arrows step. Backspace clears.</p>
        </aside>
      </div>
    {/if}
  {/if}
  {#if error}
    <p class="error">{error}</p>
  {/if}
</main>

<style>
  g.hidden {
    visibility: hidden;
  }

  :global(body) {
    margin: 0;
    background: #111;
    color: #eee;
    font-family: system-ui, sans-serif;
  }

  main {
    box-sizing: border-box;
    height: 100vh;
    display: flex;
    flex-direction: column;
    padding: 12px 16px 16px;
    overflow: hidden;
  }

  a {
    color: #8cf;
  }

  .nav {
    margin: 0 0 8px;
  }

  .picker {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }

  select {
    font: inherit;
    flex: 1;
    min-width: 0;
    padding: 8px 10px;
    border: 0;
    background: #eee;
    color: #111;
  }

  .work {
    flex: 1;
    min-height: 0;
    display: flex;
    gap: 20px;
    align-items: stretch;
  }

  .viewport {
    position: relative;
    height: 100%;
    max-height: 100%;
    background: #000;
    overflow: hidden;
    flex: 0 0 auto;
  }

  .sheet {
    position: absolute;
    left: 0;
    top: 0;
    cursor: crosshair;
    outline: none;
  }

  img,
  svg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    image-rendering: pixelated;
    user-select: none;
  }

  svg {
    pointer-events: none;
  }

  .mag {
    position: fixed;
    z-index: 5;
    width: 160px;
    height: 160px;
    pointer-events: none;
    border: 2px solid #fc6;
    background: #000;
    image-rendering: pixelated;
  }

  .mag.off {
    display: none;
  }

  aside {
    width: 18rem;
    flex: 0 0 18rem;
    overflow: auto;
  }

  .banner {
    margin: 0;
    font-size: 2.6rem;
    line-height: 1.1;
    font-weight: 650;
    color: #fc6;
    font-variant-numeric: tabular-nums;
  }

  .meta,
  .hint {
    margin: 12px 0 0;
    font-variant-numeric: tabular-nums;
  }

  .hint {
    color: #bbb;
    line-height: 1.4;
  }

  .field {
    display: grid;
    grid-template-columns: 7rem 1fr 2.5rem;
    align-items: center;
    gap: 8px;
    margin-top: 16px;
  }

  .field input {
    width: 100%;
  }

  .value {
    font-variant-numeric: tabular-nums;
    text-align: right;
  }

  button {
    font: inherit;
    font-size: 1.05rem;
    margin-top: 16px;
    padding: 12px 20px;
    border: 0;
    background: #eee;
    color: #111;
    cursor: pointer;
  }

  button.on {
    background: #fc6;
  }

  .error {
    color: #f88;
  }
</style>
