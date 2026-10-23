<script>
  const NATIVE_W = 2592;
  const NATIVE_H = 1944;

  let sweeps = $state([]);
  let clips = $state([]);
  let clipId = $state("");
  let index = $state(0);
  let playing = $state(true);
  let showClick = $state(true);
  let showGlint = $state(true);
  let showHog = $state(true);
  let loaded = $state(false);
  let error = $state("");

  let sweep = $derived(sweeps.find((item) => item.id === clipId) ?? null);
  let clip = $derived(clips.find((item) => item.id === clipId) ?? null);
  let frame = $derived(sweep?.frames?.[index] ?? null);
  let file = $derived(frame?.file ?? "");
  let total = $derived(sweep?.frames?.length ?? 0);
  let interval = $derived(sweep?.interval > 0 ? sweep.interval : 0.4);
  let fps = $derived(interval > 0 ? 1 / interval : 2.5);
  let cropSize = $derived.by(() => {
    if (!clip?.crop) return { w: 1, h: 1 };
    const [x0, , x1, y1] = clip.crop;
    return { w: Math.max(1, x1 - x0), h: Math.max(1, y1) };
  });
  let click = $derived(frame ? toCrop(frame.click) : null);
  let glint = $derived(frame ? toCrop(frame.glint) : null);
  let hog = $derived(frame ? toCrop(frame.hog) : null);
  let glintDy = $derived(gap(frame?.glint));
  let hogDy = $derived(gap(frame?.hog));

  $effect(() => {
    let stop = false;
    Promise.all([fetch("/playback").then((res) => res.json()), fetch("/recordings").then((res) => res.json())])
      .then(([playback, data]) => {
        if (stop) return;
        if (playback.error) throw new Error(playback.error);
        const known = new Set((data.clips ?? []).map((item) => item.id));
        sweeps = (playback.sweeps ?? []).filter((item) => known.has(item.id));
        clips = data.clips ?? [];
        if (!clipId && sweeps.length) clipId = sweeps[0].id;
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
    clipId;
    index = 0;
  });

  $effect(() => {
    if (!playing || total < 2) return;
    const wait = interval * 1000;
    const here = index;
    const timer = setTimeout(() => {
      index = (here + 1) % total;
    }, wait);
    return () => clearTimeout(timer);
  });

  $effect(() => {
    if (!sweep || total < 2) return;
    const next = sweep.frames[(index + 1) % total];
    if (!next) return;
    const img = new Image();
    img.src = `/recordings/${sweep.id}/${next.file}`;
  });

  function toCrop(point) {
    if (!clip?.crop || !point) return null;
    const [x0, y0] = clip.crop;
    return {
      x: point[0] * (clip.frameWidth / NATIVE_W) - x0,
      y: point[1] * (clip.frameHeight / NATIVE_H) - y0,
    };
  }

  function inside(point) {
    return point && point.x >= -80 && point.y >= -80 && point.x <= cropSize.w + 80 && point.y <= cropSize.h + 80;
  }

  function gap(point) {
    if (!frame?.click || !point) return null;
    return Math.abs(point[1] - frame.click[1]);
  }

  function sweepLabel(item) {
    const clock = item.id.replace(/^\d{8}-/, "");
    return `${clock} · ${item.frames.length} frames`;
  }

  function step(delta) {
    if (!total) return;
    playing = false;
    index = (index + delta + total) % total;
  }

  function onKey(event) {
    const tag = event.target?.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "BUTTON") return;
    if (event.key === " ") {
      event.preventDefault();
      playing = !playing;
    } else if (event.key === "ArrowRight") {
      step(1);
    } else if (event.key === "ArrowLeft") {
      step(-1);
    } else if (event.key === "c") {
      showClick = !showClick;
    } else if (event.key === "g") {
      showGlint = !showGlint;
    } else if (event.key === "h") {
      showHog = !showHog;
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<main>
  <p class="nav"><a href="/main">Main</a> · <a href="/">Camera</a> · <a href="/label">Label</a></p>
  {#if !loaded}
    <p>Loading…</p>
  {:else if sweeps.length === 0}
    <p>No sweep playback yet.</p>
  {:else}
    <label class="picker">
      Sweep
      <select
        bind:value={clipId}
        onchange={(event) => event.currentTarget.blur()}
      >
        {#each sweeps as item (item.id)}
          <option value={item.id}>{sweepLabel(item)}</option>
        {/each}
      </select>
    </label>
    {#if sweep && clip && file}
      <div class="work">
        <div class="viewport" style="aspect-ratio: {cropSize.w} / {cropSize.h}">
          {#key file}
            <img src={`/recordings/${clip.id}/${file}`} alt={file} draggable="false" />
          {/key}
          <svg viewBox="0 0 {cropSize.w} {cropSize.h}" preserveAspectRatio="none">
            {#if showClick && inside(click)}
              <circle cx={click.x} cy={click.y} r="26" fill="none" stroke="#fc6" stroke-width="2" vector-effect="non-scaling-stroke" />
              <circle cx={click.x} cy={click.y} r="2" fill="#fc6" />
            {/if}
            {#if showGlint && inside(glint)}
              <circle cx={glint.x} cy={glint.y} r="18" fill="none" stroke="#28dcff" stroke-width="2" vector-effect="non-scaling-stroke" />
              <circle cx={glint.x} cy={glint.y} r="2" fill="#28dcff" />
            {/if}
            {#if showHog && inside(hog)}
              <circle cx={hog.x} cy={hog.y} r="12" fill="none" stroke="#dc3cdc" stroke-width="2" vector-effect="non-scaling-stroke" />
              <circle cx={hog.x} cy={hog.y} r="2" fill="#dc3cdc" />
            {/if}
          </svg>
        </div>
        <aside>
          <p class="meta">{fps.toFixed(1)} fps · frame {index + 1} / {total}</p>
          <button
            type="button"
            class:on={playing}
            onclick={(event) => {
              playing = !playing;
              event.currentTarget.blur();
            }}
          >{playing ? "Pause" : "Play"}</button>
          <label class="field">
            <span>Frame</span>
            <input
              type="range"
              min="0"
              max={Math.max(0, total - 1)}
              step="1"
              value={index}
              oninput={(event) => {
                playing = false;
                index = Number(event.currentTarget.value);
              }}
            />
            <span class="value">{index + 1}</span>
          </label>
          <p class="steps">
            <button type="button" class="click" class:on={showClick} onclick={(event) => { showClick = !showClick; event.currentTarget.blur(); }}>Click</button>
            <button type="button" class="glint" class:on={showGlint} onclick={(event) => { showGlint = !showGlint; event.currentTarget.blur(); }}>Glint</button>
            <button type="button" class="hog" class:on={showHog} onclick={(event) => { showHog = !showHog; event.currentTarget.blur(); }}>HOG</button>
          </p>
          {#if glintDy != null}
            <p class="meta glint">glint {glintDy.toFixed(0)} px</p>
          {/if}
          {#if hogDy != null}
            <p class="meta hog">HOG {hogDy.toFixed(0)} px</p>
          {/if}
          <p class="hint">Yellow is your click, cyan is glint, magenta is HOG. The numbers are how far that mark sits from the click, in native pixels. Space plays. Arrows step.</p>
        </aside>
      </div>
    {/if}
  {/if}
  {#if error}
    <p class="error">{error}</p>
  {/if}
</main>

<style>
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

  aside {
    width: 18rem;
    flex: 0 0 18rem;
    overflow: auto;
  }

  .meta,
  .hint {
    margin: 12px 0 0;
    font-variant-numeric: tabular-nums;
  }

  .meta.glint {
    color: #28dcff;
  }

  .meta.hog {
    color: #dc3cdc;
  }

  .hint {
    color: #bbb;
    line-height: 1.4;
  }

  .field {
    display: grid;
    grid-template-columns: 4.5rem 1fr 2.5rem;
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
    background: #333;
    color: #eee;
    cursor: pointer;
  }

  button.on {
    background: #eee;
    color: #111;
  }

  .steps {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .steps button {
    margin-top: 16px;
  }

  button.click.on {
    background: #fc6;
    color: #111;
  }

  button.glint.on {
    background: #28dcff;
    color: #111;
  }

  button.hog.on {
    background: #dc3cdc;
    color: #111;
  }

  .error {
    color: #f88;
  }
</style>
