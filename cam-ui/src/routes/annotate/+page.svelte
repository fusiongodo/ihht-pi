<script>
  const WIDTH = 2592;
  const HEIGHT = 1944;

  let files = $state([]);
  let balls = $state({});
  let scales = $state({});
  let corners = $state([]);
  let index = $state(0);
  let overlay = $state(null);
  let dragging = $state(false);
  let error = $state("");
  let note = $state("");

  let file = $derived(files[index] ?? "");
  let point = $derived(balls[file] ?? null);
  let polygon = $derived(corners.map((corner) => corner.join(",")).join(" "));
  let marked = $derived(files.filter((name) => balls[name]).length);

  $effect(() => {
    let stop = false;
    Promise.all([
      fetch("/annotations").then((res) => res.json()),
      fetch("/bbox").then((res) => res.json()),
    ])
      .then(([annotations, box]) => {
        if (stop) return;
        files = annotations.files ?? [];
        balls = annotations.balls ?? {};
        scales = annotations.scales ?? {};
        corners = Array.isArray(box.corners) ? box.corners : [];
      })
      .catch((err) => {
        if (!stop) error = err instanceof Error ? err.message : String(err);
      });
    return () => {
      stop = true;
    };
  });

  function step(delta) {
    if (!files.length) return;
    index = (index + delta + files.length) % files.length;
    note = "";
  }

  function onKey(event) {
    if (event.target instanceof HTMLInputElement) return;
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    step(event.key === "ArrowLeft" ? -1 : 1);
  }

  async function commitScale(event) {
    if (!file) return;
    const raw = event.currentTarget.value.trim().replace(",", ".");
    const current = file;
    error = "";
    let scale = null;
    if (raw !== "") {
      if (!/^-?\d+(\.\d+)?$/.test(raw)) {
        error = "Scale must be a number";
        return;
      }
      scale = Number(raw);
    }
    try {
      const res = await fetch("/annotations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: current, scale }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      const next = { ...scales };
      if (data.scale === null) delete next[current];
      else next[current] = data.scale;
      scales = next;
      if (file === current) note = "Saved";
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  function pointFrom(event) {
    const box = overlay.getBoundingClientRect();
    const x = Math.round(((event.clientX - box.left) / box.width) * WIDTH);
    const y = Math.round(((event.clientY - box.top) / box.height) * HEIGHT);
    return [Math.min(WIDTH, Math.max(0, x)), Math.min(HEIGHT, Math.max(0, y))];
  }

  async function savePoint(next, current) {
    balls = { ...balls, [current]: next };
    const res = await fetch("/annotations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: current, point: next }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    balls = { ...balls, [current]: data.point };
    if (file === current) note = "Saved";
  }

  async function place(event) {
    if (dragging || !file) return;
    error = "";
    try {
      await savePoint(pointFrom(event), file);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  function startDrag(event) {
    event.stopPropagation();
    event.preventDefault();
    dragging = true;
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      overlay.setPointerCapture(event.pointerId);
    }
  }

  function moveDrag(event) {
    if (!dragging || !file) return;
    balls = { ...balls, [file]: pointFrom(event) };
  }

  async function endDrag() {
    if (!dragging || !file) return;
    const current = file;
    const next = balls[current];
    dragging = false;
    error = "";
    try {
      await savePoint(next, current);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }
</script>

<svelte:window onkeydown={onKey} />

<main>
  <p class="nav"><a href="/main">Main</a> · <a href="/">Camera</a></p>
  {#if file}
    <div class="stage">
      <img src={`/shots/${file}`} alt={file} />
      <svg
        bind:this={overlay}
        viewBox="0 0 {WIDTH} {HEIGHT}"
        preserveAspectRatio="none"
        onclick={place}
        onpointermove={moveDrag}
        onpointerup={endDrag}
      >
        {#if corners.length === 4}
          <polygon
            points={polygon}
            fill="rgba(80, 180, 255, 0.15)"
            stroke="#8cf"
            stroke-width="2"
            vector-effect="non-scaling-stroke"
          />
        {/if}
        {#if point}
          <circle
            role="button"
            aria-label="ball"
            cx={point[0]}
            cy={point[1]}
            r="36"
            fill="#fc6"
            stroke="#111"
            stroke-width="2"
            vector-effect="non-scaling-stroke"
            onpointerdown={startDrag}
            onclick={(event) => event.stopPropagation()}
          />
        {/if}
      </svg>
    </div>
    <p class="meta">{file} · {index + 1} / {files.length} · {marked} marked</p>
    <p class="meta">{point ? `${point[0]}, ${point[1]}` : "Click the ball"}{note ? ` · ${note}` : ""}</p>
    <label class="scale">
      Scale
      {#key file}
        <input type="number" step="any" value={scales[file] ?? ""} onchange={commitScale} />
      {/key}
    </label>
    <div class="actions">
      <button type="button" onclick={() => step(-1)}>Previous</button>
      <button type="button" onclick={() => step(1)}>Next</button>
    </div>
  {:else}
    <p>No shots yet.</p>
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
    max-width: 720px;
    margin: 0 auto;
    padding: 24px 16px 48px;
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

  img,
  svg {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }

  img {
    display: block;
    object-fit: contain;
  }

  svg {
    touch-action: none;
  }

  circle {
    cursor: grab;
  }

  .meta {
    margin: 12px 0 0;
    font-variant-numeric: tabular-nums;
  }

  .scale {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
  }

  input {
    font: inherit;
    width: 6rem;
    padding: 8px 10px;
    border: 0;
    background: #eee;
    color: #111;
  }

  .actions {
    display: flex;
    gap: 8px;
    margin-top: 16px;
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

  .error {
    color: #f88;
  }
</style>
