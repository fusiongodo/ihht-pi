"""Score one MOSSE kernel per size on the held-out sweep.

σ = 2 px and λ = 0.01 stay fixed. Width and height run from 1× to 3× the
88 px ball, independently. Each kernel is applied with normalized
cross-correlation. Fit on one sweep plus the steady clips, score the other
sweep, then swap.
"""
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from search_clips import (
    BORE,
    NATIVE_H,
    center_on_strip,
    glint_kernel,
    jitter,
    load_frames,
    load_json,
    make_hog,
    native_of,
    odd,
    peak_at,
    response_of,
    search_hog,
    subpixel,
    train_hog,
)

HEIGHT = 972
DIAMETER = 88
SCALES = tuple(1 + 0.25 * step for step in range(9))
SIGMA = 2.0
LAM = 0.01
GLINT = 2.5
DISK = 40
HOG_WIN = 32
HOG_LOOK = 160
BALL_RADIUS = DIAMETER * HEIGHT / NATIVE_H / 2
CORE_RADIUS = 2.5


def cosine_window(height, width):
    return np.outer(np.hanning(height), np.hanning(width))


def desired_peak(height, width, sigma):
    yy, xx = np.ogrid[:height, :width]
    cy, cx = height // 2, width // 2
    return np.exp(-((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * sigma * sigma))


def preprocess(patch, window):
    values = np.asarray(patch, np.float64)
    values = values - values.mean()
    norm = float(np.linalg.norm(values))
    if norm < 1e-6:
        return np.zeros_like(values)
    return values / norm * window


def train_mosse(patches, sigma, lam):
    """Return the float32 kernel, shape (height, width), center on the click.

    The solved filter is conjugated because matchTemplate correlates, then
    shifted so the click sits in the middle, then multiplied by the cosine window.
    """
    height, width = patches[0].shape[:2]
    window = cosine_window(height, width)
    goal = np.fft.fft2(desired_peak(height, width, sigma))
    numer = np.zeros((height, width), np.complex128)
    denom = np.zeros((height, width), np.complex128)
    used = 0
    for patch in patches:
        sample = preprocess(patch, window)
        if not np.any(sample):
            continue
        freq = np.fft.fft2(sample)
        numer += goal * np.conj(freq)
        denom += freq * np.conj(freq)
        used += 1
    if used == 0:
        raise RuntimeError("MOSSE received no usable patches")
    solved = numer / (denom + lam)
    spatial = np.fft.fftshift(np.fft.ifft2(np.conj(solved)).real)
    spatial *= window
    return np.ascontiguousarray(spatial, np.float32), used


def ncc_peak(image, kernel):
    response = cv2.matchTemplate(image, kernel, cv2.TM_CCOEFF_NORMED)
    kh, kw = kernel.shape[:2]
    height, width = image.shape[:2]
    half_x = (kw - 1) / 2
    half_y = (kh - 1) / 2
    x0 = width * BORE[0]
    x1 = width * BORE[1]
    c0 = max(0, int(np.ceil(x0 - half_x)))
    c1 = min(response.shape[1], int(np.floor(x1 - half_x)) + 1)
    if c1 <= c0 or response.shape[0] < 1:
        return width / 2, height / 2, -1.0
    view = np.nan_to_num(response[:, c0:c1], nan=-1.0, posinf=-1.0, neginf=-1.0)
    row, col = np.unravel_index(int(np.argmax(view)), view.shape)
    col = c0 + int(col)
    row = int(row)
    col_f = subpixel(np.nan_to_num(response[row], nan=-1.0), col)
    row_f = subpixel(np.nan_to_num(response[:, col], nan=-1.0), row)
    score = float(view[int(np.unravel_index(int(np.argmax(view)), view.shape)[0]), int(col - c0)])
    return float(col_f + half_x), float(row_f + half_y), score


def self_check():
    rng = np.random.default_rng(0)
    height, width, side = 180, 90, 41

    def scene(ball_y):
        image = np.full((height, width), 140, np.float32)
        image += rng.normal(0, 2, image.shape)
        for row in range(8, height, 14):
            image[row : row + 1, 25:65] -= 35
        yy, xx = np.ogrid[:height, :width]
        image[(yy - ball_y) ** 2 + (xx - 45) ** 2 <= 12 ** 2] = 45
        image[ball_y - 4 : ball_y - 1, 49:53] = 210
        return image

    patches = [cv2.getRectSubPix(scene(ball_y), (side, side), (45.0, float(ball_y))) for ball_y in range(30, 150, 6)]
    kernel, used = train_mosse(patches, SIGMA, LAM)
    test = scene(110)
    test[48:56, 30:38] = 245
    x, y, score = ncc_peak(test, kernel)
    err = max(abs(x - 45), abs(y - 110))
    print(f"self-check peak error {err:.2f} px score {score:.3f}", flush=True)
    if used != len(patches) or err > 1.5 or score < 0.2:
        raise SystemExit("MOSSE self-check failed")


def strip_side(native):
    return odd(native * HEIGHT / NATIVE_H)


def patch_at_click(frame, clip, kh, kw):
    cx, cy = center_on_strip(frame, clip, HEIGHT)
    if not (0 <= cx < frame["strips"][HEIGHT].shape[1] and 0 <= cy < frame["strips"][HEIGHT].shape[0]):
        return None
    return cv2.getRectSubPix(frame["strips"][HEIGHT], (kw, kh), (float(cx), float(cy)))


def speck_contrast(frame, clip):
    side = odd(BALL_RADIUS * 2)
    patch = patch_at_click(frame, clip, side, side)
    if patch is None:
        return None
    yy, xx = np.ogrid[:side, :side]
    center = side // 2
    dist = (yy - center) ** 2 + (xx - center) ** 2
    disk = patch[dist <= BALL_RADIUS ** 2]
    core = patch[dist <= CORE_RADIUS ** 2]
    if disk.size == 0 or core.size == 0:
        return None
    return float(np.max(core) - np.median(disk))


def speck_cut(values):
    values = np.asarray([value for value in values if value is not None], np.float64)
    if values.size == 0:
        return 0.0, "quartile", [], []
    lo, hi = np.percentile(values, [1, 99])
    if not np.isfinite(lo) or hi <= lo:
        return float(np.percentile(values, 25)), "quartile", [], []
    counts, edges = np.histogram(values, bins=30, range=(float(lo), float(hi)))
    smooth = np.convolve(counts.astype(np.float64), [1, 2, 3, 2, 1], mode="same") / 9
    peaks = []
    for index in range(1, len(smooth) - 1):
        if smooth[index] >= smooth[index - 1] and smooth[index] >= smooth[index + 1] and smooth[index] > 0:
            peaks.append(index)
    peaks.sort(key=lambda index: smooth[index], reverse=True)
    if len(peaks) >= 2:
        left, right = sorted(peaks[:2])
        if right > left + 2:
            valley = left + int(np.argmin(smooth[left : right + 1]))
            if smooth[valley] < 0.7 * min(smooth[left], smooth[right]):
                cut = float((edges[valley] + edges[valley + 1]) / 2)
                return cut, "valley", counts.tolist(), [round(float(edge), 2) for edge in edges]
    return float(np.percentile(values, 25)), "quartile", counts.tolist(), [round(float(edge), 2) for edge in edges]


def bin_shares(errors):
    values = [abs(error) for error in errors]
    count = len(values)
    if count == 0:
        return None
    shares = [0, 0, 0, 0]
    for value in values:
        if value <= 5:
            shares[0] += 1
        elif value <= 10:
            shares[1] += 1
        elif value <= 20:
            shares[2] += 1
        else:
            shares[3] += 1
    return {
        "n": count,
        "bins": [round(100.0 * item / count, 1) for item in shares],
        "med": round(float(np.median(values)), 2),
    }


def native_point(sx, sy, frame, clip):
    return native_of(sx, sy, frame["inverses"][HEIGHT], clip["origin"], clip["scale"])


def train_patches(clips, kh, kw):
    patches = []
    for clip in clips:
        for frame in clip["frames"]:
            patch = patch_at_click(frame, clip, kh, kw)
            if patch is not None:
                patches.append(patch)
    return patches


def locate_kernel(kernel, clips):
    found = {}
    for clip in clips:
        rows = []
        for frame in clip["frames"]:
            started = time.perf_counter()
            sx, sy, _score = ncc_peak(frame["gray"], kernel)
            elapsed = time.perf_counter() - started
            _nx, ny = native_point(sx, sy, frame, clip)
            rows.append({"file": frame["file"], "y": ny, "ly": frame["ly"], "covered": frame["covered"], "ms": elapsed * 1000})
        found[clip["id"]] = rows
    return found


def locate_glint(kernel, clips):
    margin = kernel.shape[0] // 2
    found = {}
    for clip in clips:
        rows = []
        for frame in clip["frames"]:
            started = time.perf_counter()
            response = response_of(frame["strips"][HEIGHT], kernel)
            sx, sy, _score = peak_at(response, 0, frame["strips"][HEIGHT].shape[0], margin)
            elapsed = time.perf_counter() - started
            _nx, ny = native_point(sx, sy, frame, clip)
            rows.append({"file": frame["file"], "y": ny, "ly": frame["ly"], "covered": frame["covered"], "ms": elapsed * 1000})
        found[clip["id"]] = rows
    return found


def shift_of(rows):
    if not rows:
        return 0.0
    return float(np.median([row["ly"] - row["y"] for row in rows]))


def holds_from(found, clips, use_shift):
    sweeps = [clip for clip in clips if clip["kind"] == "sweep"]
    steadies = [clip for clip in clips if clip["kind"] == "steady"]
    holds = []
    for hold in sweeps:
        train_ids = [clip["id"] for clip in sweeps if clip["id"] != hold["id"]]
        train_ids += [clip["id"] for clip in steadies]
        train_rows = [row for clip_id in train_ids for row in found[clip_id]]
        shift = shift_of(train_rows) if use_shift else 0.0
        test = found[hold["id"]]
        errors = [row["ly"] - (row["y"] + shift) for row in test]
        visible = [error for error, row in zip(errors, test) if not row["covered"]]
        covered = [error for error, row in zip(errors, test) if row["covered"]]
        groups = []
        for clip in steadies:
            groups.append([row["y"] + shift for row in found[clip["id"]]])
        spread, _worst = jitter(groups)
        holds.append(
            {
                "name": str(len(hold["frames"])),
                "id": hold["id"],
                "errors": errors,
                "visible": visible,
                "covered": covered,
                "times": [row["ms"] for row in test],
                "jitter": None if spread is None else round(spread, 2),
                "shift": round(shift, 2),
            }
        )
    return holds


def row_from(holds, method, fields):
    errors = [error for hold in holds for error in hold["errors"]]
    visible = [error for hold in holds for error in hold["visible"]]
    covered = [error for hold in holds for error in hold["covered"]]
    times = [item for hold in holds for item in hold["times"]]
    jitters = [hold["jitter"] for hold in holds if hold["jitter"] is not None]
    shares = bin_shares(errors)
    row = {
        "method": method,
        **fields,
        "bins": shares["bins"],
        "n": shares["n"],
        "med": shares["med"],
        "visible": bin_shares(visible),
        "covered": bin_shares(covered),
        "sweeps": {hold["name"]: bin_shares(hold["errors"]) for hold in holds},
        "ms": round(float(np.median(times)), 2) if times else None,
        "jitter": None if not jitters else round(float(np.median(jitters)), 2),
        "shift": [hold["shift"] for hold in holds],
    }
    return row


def format_line(row):
    bins = " ".join(f"{value:5.1f}" for value in row["bins"])
    width = "-" if row.get("native_w") is None else f"{row['native_w']:>4}"
    height = "-" if row.get("native_h") is None else f"{row['native_h']:>4}"
    return (
        f"{row['method']:8} w {width} h {height} "
        f"[{bins}] >20 {row['bins'][3]:5.1f}  <=5 {row['bins'][0]:5.1f}  ms {row['ms']}"
    )


def hog_holds(clips):
    sweeps = [clip for clip in clips if clip["kind"] == "sweep"]
    steadies = [clip for clip in clips if clip["kind"] == "steady"]
    hog = make_hog(HOG_WIN)
    radius = HOG_LOOK * HEIGHT / NATIVE_H
    holds = []
    for hold in sweeps:
        train = [clip for clip in sweeps if clip["id"] != hold["id"]] + steadies
        samples = [(frame["strips"][HEIGHT], center_on_strip(frame, clip, HEIGHT)) for clip in train for frame in clip["frames"]]
        started = time.perf_counter()
        svm, sign, margin = train_hog(hog, samples, HOG_WIN)
        print(f"hog trained aside {hold['id'][-15:]} in {time.perf_counter() - started:.1f}s margin {margin:.2f}", flush=True)
        per_clip = {}
        for clip in [hold] + steadies:
            last_y = None
            rows = []
            for frame in clip["frames"]:
                strip = frame["strips"][HEIGHT]
                started = time.perf_counter()
                full = last_y is None
                if not full:
                    sx, sy, score = search_hog(hog, svm, sign, strip, last_y - radius, last_y + radius, HOG_WIN)
                    if score < margin:
                        full = True
                if full:
                    sx, sy, score = search_hog(hog, svm, sign, strip, 0, strip.shape[0] - HOG_WIN, HOG_WIN)
                elapsed = time.perf_counter() - started
                last_y = sy
                _nx, ny = native_point(sx, sy, frame, clip)
                rows.append({"file": frame["file"], "y": ny, "ly": frame["ly"], "covered": frame["covered"], "ms": elapsed * 1000})
            per_clip[clip["id"]] = rows
        test = per_clip[hold["id"]]
        errors = [row["ly"] - row["y"] for row in test]
        groups = [[row["y"] for row in per_clip[clip["id"]]] for clip in steadies]
        spread, _worst = jitter(groups)
        holds.append(
            {
                "name": str(len(hold["frames"])),
                "id": hold["id"],
                "errors": errors,
                "visible": [error for error, row in zip(errors, test) if not row["covered"]],
                "covered": [error for error, row in zip(errors, test) if row["covered"]],
                "times": [row["ms"] for row in test],
                "jitter": None if spread is None else round(spread, 2),
                "shift": 0.0,
            }
        )
    return holds


def learned_rows(clips):
    rows = []
    natives = [int(round(DIAMETER * scale)) for scale in SCALES]
    total = len(natives) * len(natives)
    done = 0
    for native_h in natives:
        for native_w in natives:
            done += 1
            kh, kw = strip_side(native_h), strip_side(native_w)
            rows.append(score_one_size(clips, native_w, native_h, kh, kw, done, total))
    return rows


def score_one_size(clips, native_w, native_h, kh, kw, done, total):
    sweeps = [clip for clip in clips if clip["kind"] == "sweep"]
    steadies = [clip for clip in clips if clip["kind"] == "steady"]
    started = time.perf_counter()
    per_hold_found = []
    used_counts = []
    for hold in sweeps:
        train = [clip for clip in sweeps if clip["id"] != hold["id"]] + steadies
        kernel, used = train_mosse(train_patches(train, kh, kw), SIGMA, LAM)
        used_counts.append(used)
        found = {}
        for clip in [hold] + train:
            if clip["id"] in found:
                continue
            found.update(locate_kernel(kernel, [clip]))
        per_hold_found.append(found)
    holds = []
    for hold, found in zip(sweeps, per_hold_found):
        train_ids = [clip["id"] for clip in sweeps if clip["id"] != hold["id"]] + [clip["id"] for clip in steadies]
        shift = shift_of([row for clip_id in train_ids for row in found[clip_id]])
        test = found[hold["id"]]
        errors = [row["ly"] - (row["y"] + shift) for row in test]
        groups = [[row["y"] + shift for row in found[clip["id"]]] for clip in steadies]
        spread, _worst = jitter(groups)
        holds.append(
            {
                "name": str(len(hold["frames"])),
                "id": hold["id"],
                "errors": errors,
                "visible": [error for error, row in zip(errors, test) if not row["covered"]],
                "covered": [error for error, row in zip(errors, test) if row["covered"]],
                "times": [row["ms"] for row in test],
                "jitter": None if spread is None else round(spread, 2),
                "shift": round(shift, 2),
            }
        )
    row = row_from(
        holds,
        "learned",
        {
            "native_w": native_w,
            "native_h": native_h,
            "strip_w": kw,
            "strip_h": kh,
            "patches": used_counts,
        },
    )
    print(
        f"{done:3}/{total} {time.perf_counter() - started:5.1f}s  {format_line(row)}",
        flush=True,
    )
    return row


def mark_speck(clips, cut):
    for clip in clips:
        for frame in clip["frames"]:
            contrast = speck_contrast(frame, clip)
            frame["contrast"] = contrast
            frame["covered"] = contrast is not None and contrast < cut
            frame["gray"] = frame["strips"][HEIGHT].astype(np.float32)


def html_of(payload):
    def cells(shares):
        if not shares:
            return "<td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>"
        bins = "".join(f"<td>{value:.1f}</td>" for value in shares["bins"])
        return f"<td>{shares['n']}</td>{bins}"

    def sweep_cell(row, name, index):
        shares = row["sweeps"].get(name)
        if not shares:
            return "<td>—</td>"
        return f"<td>{shares['bins'][index]:.1f}</td>"

    learned = [row for row in payload["rows"] if row["method"] == "learned"]
    learned.sort(key=lambda row: (row["bins"][3], -row["bins"][0], row["ms"] or 0))
    best = learned[0] if learned else None
    refs = [row for row in payload["rows"] if row["method"] != "learned"]
    ordered = refs + learned

    def heat():
        natives = sorted({row["native_w"] for row in learned})
        lookup = {(row["native_w"], row["native_h"]): row["bins"][3] for row in learned}
        side = 46
        pad = 36
        width = pad + side * len(natives)
        height = pad + side * len(natives)
        parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Share of misses above 20 px by kernel size">']
        for row_index, native_h in enumerate(natives):
            for col_index, native_w in enumerate(natives):
                value = lookup.get((native_w, native_h), 0)
                tone = min(value / 40, 1)
                red = int(47 + tone * (140 - 47))
                green = int(111 - tone * 70)
                blue = int(78 - tone * 40)
                x = pad + col_index * side
                y = pad + row_index * side
                parts.append(
                    f'<rect x="{x}" y="{y}" width="{side - 3}" height="{side - 3}" fill="rgb({red},{green},{blue})"/>'
                )
                label = f"{value:.0f}" if value >= 10 else f"{value:.1f}"
                parts.append(
                    f'<text x="{x + (side - 3) / 2}" y="{y + (side + 6) / 2}" text-anchor="middle" font-size="10" fill="#fff">{label}</text>'
                )
            parts.append(
                f'<text x="{pad - 6}" y="{pad + row_index * side + side / 2}" text-anchor="end" font-size="11" fill="#6b675f">{native_h}</text>'
            )
        for col_index, native_w in enumerate(natives):
            parts.append(
                f'<text x="{pad + col_index * side + side / 2}" y="{pad - 10}" text-anchor="middle" font-size="11" fill="#6b675f">{native_w}</text>'
            )
        parts.append(f'<text x="{pad}" y="12" font-size="11" fill="#6b675f">width →</text>')
        parts.append(f'<text x="12" y="{height - 8}" font-size="11" fill="#6b675f" transform="rotate(-90 12 {height - 8})">height</text>')
        parts.append("</svg>")
        return "".join(parts)

    body_rows = []
    for row in ordered:
        label = row["method"]
        if row["method"] == "learned":
            label = f"{row['native_w']}×{row['native_h']}"
        cls = ' class="best"' if best is row else ""
        vis = cells(row["visible"])
        cov = cells(row["covered"])
        bins = "".join(f"<td>{value:.1f}</td>" for value in row["bins"])
        body_rows.append(
            "<tr"
            + cls
            + ">"
            + f"<td>{label}</td><td>{row['strip_w'] if row.get('strip_w') else '—'}</td><td>{row['strip_h'] if row.get('strip_h') else '—'}</td>"
            + bins
            + f"<td>{row['ms'] if row['ms'] is not None else '—'}</td>"
            + vis
            + cov
            + sweep_cell(row, "100", 3)
            + sweep_cell(row, "200", 3)
            + "</tr>"
        )
    cut = payload["speck"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>MOSSE kernel search</title>
<style>
:root {{ color-scheme: light; }}
body {{ margin: 0; font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1c1c1c; background: #f6f5f3; }}
main {{ max-width: 1280px; margin: 0 auto; padding: 32px 24px 64px; }}
h1 {{ font-size: 28px; font-weight: 650; letter-spacing: -0.02em; margin: 0 0 8px; }}
h2 {{ font-size: 18px; font-weight: 650; margin: 28px 0 6px; }}
p {{ margin: 0 0 12px; color: #4c4a46; }}
p.note {{ font-size: 13px; }}
.table-wrap {{ overflow-x: auto; border: 1px solid #e2dfd8; border-radius: 8px; background: #fff; }}
table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; font-size: 13px; }}
th, td {{ padding: 6px 8px; text-align: right; white-space: nowrap; border-bottom: 1px solid #eeeae4; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ font-size: 11px; letter-spacing: 0.02em; text-transform: uppercase; color: #6b675f; background: #faf9f7; position: sticky; top: 0; }}
tr.best td {{ background: #e7f3ea; }}
svg {{ width: min(100%, 560px); height: auto; background: #fff; border: 1px solid #e2dfd8; border-radius: 8px; }}
</style>
</head>
<body>
<main>
<h1>MOSSE kernel search</h1>
<p>One kernel per width and height. MOSSE training uses σ = 2 px and λ = 0.01. The cosine window is multiplied into the kernel once after training. Detection is normalized cross-correlation over the bore. Each kernel is fit on one sweep plus the steady clips and scored on the other sweep, then the sweeps swap. Bins are the share of held-out sweep frames whose vertical miss is in that range, in native pixels on the 2592×1944 frame. Mac milliseconds are one OpenCV thread. Source: the labeled clips recorded on 22 Oct 2026.</p>
<h2>Misses above 20 px</h2>
<p class="note">Each cell is one kernel. The number is the percent of held-out frames more than 20 px off. Width and height are native pixels, from 1× to 3× the 88 px ball. Darker is worse.</p>
{heat()}
<h2>Glint, HOG, and every learned size</h2>
<p class="note">Glint is strip 972, glint 2.5, disk 40, full bore. HOG is a 32 px patch searching ±160 px from the last hit, so its search is local and its time is not the same kind of cost. Learned rows search the whole bore. Strip columns are the kernel size actually applied on the 972-tall strip. Visible and covered use a speck cut of {cut['cut']:.1f} gray levels ({cut['rule']}). Covered frames: {cut['covered']} of {cut['labeled']}. Sorted by the share above 20 px, then by the share within 5 px. The highlighted row is the best learned size. 100 and 200 are the two held-out sweeps, showing only the share above 20 px.</p>
<div class="table-wrap"><table>
<thead><tr>
<th>Kernel</th><th>Strip w</th><th>Strip h</th>
<th>0–5</th><th>5–10</th><th>10–20</th><th>&gt;20</th><th>Mac ms</th>
<th>Vis n</th><th>Vis 0–5</th><th>Vis 5–10</th><th>Vis 10–20</th><th>Vis &gt;20</th>
<th>Cov n</th><th>Cov 0–5</th><th>Cov 5–10</th><th>Cov 10–20</th><th>Cov &gt;20</th>
<th>100 &gt;20</th><th>200 &gt;20</th>
</tr></thead>
<tbody>
{''.join(body_rows)}
</tbody></table></div>
</main>
</body>
</html>
"""


def main():
    self_check()
    root = Path("cam-ui/recordings")
    bbox = load_json(Path("cam-ui/bbox.json"))
    cv2.setNumThreads(1)
    print("loading", flush=True)
    clips = load_frames(root, bbox, (HEIGHT,))
    for clip in clips:
        print(f"  {clip['id']} {clip['kind']} {len(clip['frames'])}", flush=True)
    contrasts = [speck_contrast(frame, clip) for clip in clips for frame in clip["frames"]]
    finite = [value for value in contrasts if value is not None]
    cut, rule, counts, edges = speck_cut(finite)
    covered = sum(value is not None and value < cut for value in finite)
    print(f"speck cut {cut:.2f} via {rule}, covered {covered}/{len(finite)}", flush=True)
    mark_speck(clips, cut)
    rows = []
    glint = glint_kernel(HEIGHT, GLINT, DISK)
    print("glint", flush=True)
    grows = holds_from(locate_glint(glint, clips), clips, True)
    rows.append(row_from(grows, "glint", {"native_w": None, "native_h": None, "strip_w": int(glint.shape[1]), "strip_h": int(glint.shape[0])}))
    print(format_line(rows[-1]), flush=True)
    print("hog", flush=True)
    rows.append(row_from(hog_holds(clips), "hog", {"native_w": HOG_WIN, "native_h": HOG_WIN, "strip_w": HOG_WIN, "strip_h": HOG_WIN}))
    print(format_line(rows[-1]), flush=True)
    rows.extend(learned_rows(clips))
    payload = {
        "sigma": SIGMA,
        "lambda": LAM,
        "diameter": DIAMETER,
        "speck": {
            "cut": round(cut, 2),
            "rule": rule,
            "covered": covered,
            "labeled": len(finite),
            "counts": counts,
            "edges": edges,
        },
        "rows": rows,
    }
    out = Path("eval/kernel_search.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    report = Path("reports/kernel-search.html")
    report.write_text(html_of(payload))
    print(out, report, flush=True)


if __name__ == "__main__":
    main()
