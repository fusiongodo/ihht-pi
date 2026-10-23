"""Score glint and HOG settings on the labeled clips.

Settings are chosen on one sweep plus the steady clips. The other sweep is only measured.
Then the two sweeps swap.
"""
import json
import time
from pathlib import Path

import cv2
import numpy as np

NATIVE_W = 2592
NATIVE_H = 1944
BORE = (0.30, 0.70)
HEIGHTS = (320, 640, 972)
GLINTS = (2.5, 3.5, 5.0)
DISKS = (20, 28, 40)
WINDOWS = (40, 80, 160)
WINS = (32, 48, 64)
STRIDE = 8
WEAK = 0.5


def load_json(path):
    return json.loads(Path(path).read_text())


def odd(value):
    value = max(3, int(round(value)))
    return value if value % 2 else value + 1


def strip_width(corners, height):
    def span(a, b):
        return float(np.hypot(a[0] - b[0], a[1] - b[1]))

    top = span(corners[0], corners[1])
    bottom = span(corners[3], corners[2])
    left = span(corners[0], corners[3])
    right = span(corners[1], corners[2])
    ratio = (top + bottom) / 2 / max((left + right) / 2, 1)
    return max(24, int(round(height * ratio)))


def warp(image, corners, height):
    width = strip_width(corners, height)
    src = np.array(corners, np.float32)
    dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], np.float32)
    forward = cv2.getPerspectiveTransform(src, dst)
    inverse = cv2.getPerspectiveTransform(dst, src)
    strip = cv2.warpPerspective(image, forward, (width, height))
    return strip, forward, inverse


def image_point_to_native(x, y, origin, scale):
    return (x + origin[0]) * scale, (y + origin[1]) * scale


def native_point_to_image(x, y, origin, scale):
    return x / scale - origin[0], y / scale - origin[1]


def subpixel(score, index):
    if index <= 0 or index >= len(score) - 1:
        return float(index)
    left, mid, right = float(score[index - 1]), float(score[index]), float(score[index + 1])
    denom = left - 2 * mid + right
    if abs(denom) < 1e-6:
        return float(index)
    return index + 0.5 * (left - right) / denom


def glint_kernel(height, glint, disk):
    scale = height / NATIVE_H
    core = max(0.6, glint * scale)
    ring = max(core + 1.2, disk * scale)
    size = odd(ring * 2.6)
    yy, xx = np.ogrid[:size, :size]
    squared = (yy - size // 2) ** 2 + (xx - size // 2) ** 2
    kernel = np.zeros((size, size), np.float32)
    kernel[squared <= core ** 2] = 1
    kernel[(squared > core ** 2) & (squared <= ring ** 2)] = -1
    positive = float(kernel[kernel > 0].sum()) or 1.0
    negative = float(-kernel[kernel < 0].sum()) or 1.0
    kernel[kernel < 0] *= positive / negative
    return kernel


def response_of(strip, kernel):
    return cv2.filter2D(strip.astype(np.float32), cv2.CV_32F, kernel)


def peak_at(response, y0, y1, margin):
    height, width = response.shape
    x0 = int(width * BORE[0])
    x1 = max(x0 + 1, int(width * BORE[1]))
    top = max(margin, int(np.floor(y0)))
    bot = min(height - margin, int(np.ceil(y1)))
    if bot - top < 3:
        top = max(margin, top - 1)
        bot = min(height - margin, top + 3)
    view = response[top:bot, x0:x1]
    row, col = np.unravel_index(int(np.argmax(view)), view.shape)
    y = top + int(row)
    x = x0 + int(col)
    score = float(response[y, x])
    column = response[top:bot, x]
    y = top + subpixel(column, y - top)
    yi = min(bot - 1, max(top, int(round(y))))
    band = response[yi, x0:x1]
    x = x0 + subpixel(band, int(round(x)) - x0)
    return float(x), float(y), score


def native_of(x, y, inverse, origin, scale):
    point = np.array([[[x, y]]], np.float32)
    mapped = cv2.perspectiveTransform(point, inverse)[0, 0]
    return image_point_to_native(float(mapped[0]), float(mapped[1]), origin, scale)


def load_frames(root, bbox, heights):
    scale_corners = bbox["corners"]
    clips = []
    for path in sorted(Path(root).glob("*/clip.json")):
        clip = load_json(path)
        labels = {}
        label_path = path.parent / "labels.json"
        if label_path.is_file():
            labels = load_json(label_path).get("frames") or {}
        scale = NATIVE_W / clip["frameWidth"]
        origin = (clip["crop"][0], clip["crop"][1])
        corners = []
        for x, y in scale_corners:
            corners.append([x / scale - origin[0], y / scale - origin[1]])
        frames = []
        for item in clip["frames"]:
            label = labels.get(item["file"])
            if not label or label.get("absent"):
                continue
            if not np.isfinite(label.get("x", np.nan)) or not np.isfinite(label.get("y", np.nan)):
                continue
            image = cv2.imread(str(path.parent / item["file"]), cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            strips = {}
            forwards = {}
            inverses = {}
            for height in heights:
                strip, forward, inverse = warp(image, corners, height)
                strips[height] = strip
                forwards[height] = forward
                inverses[height] = inverse
            frames.append(
                {
                    "file": item["file"],
                    "lx": float(label["x"]),
                    "ly": float(label["y"]),
                    "strips": strips,
                    "forwards": forwards,
                    "inverses": inverses,
                }
            )
        if frames:
            clips.append({"id": clip["id"], "kind": clip["kind"], "frames": frames, "origin": origin, "scale": scale})
    return clips


def stats(errors):
    values = [abs(error) for error in errors]
    within = 100.0 * sum(value <= 5 for value in values) / len(values)
    return float(np.median(values)), within, float(max(values))


def jitter(groups):
    spreads = []
    for values in groups:
        if len(values) >= 2:
            spreads.append(max(values) - min(values))
    if not spreads:
        return None
    return float(np.median(spreads)), float(max(spreads))


def glint_passes(clips):
    rows = []
    sweeps = [clip for clip in clips if clip["kind"] == "sweep"]
    steadies = [clip for clip in clips if clip["kind"] == "steady"]
    for height in HEIGHTS:
        for glint in GLINTS:
            for disk in DISKS:
                kernel = glint_kernel(height, glint, disk)
                margin = kernel.shape[0] // 2
                packed = []
                started = time.perf_counter()
                for clip in clips:
                    detected = []
                    for frame in clip["frames"]:
                        strip = frame["strips"][height]
                        response = response_of(strip, kernel)
                        sx, sy, score = peak_at(response, 0, strip.shape[0], margin)
                        nx, ny = native_of(sx, sy, frame["inverses"][height], clip["origin"], clip["scale"])
                        detected.append((response, sx, sy, score, nx, ny, frame["lx"], frame["ly"]))
                    packed.append(detected)
                elapsed = time.perf_counter() - started
                per_frame = elapsed / sum(len(item) for item in packed) * 1000
                by_id = {clip["id"]: detected for clip, detected in zip(clips, packed)}
                for hold in sweeps:
                    train_ids = [clip["id"] for clip in sweeps if clip["id"] != hold["id"]] + [clip["id"] for clip in steadies]
                    train = [item for clip_id in train_ids for item in by_id[clip_id]]
                    shift_x = float(np.median([item[6] - item[4] for item in train]))
                    shift_y = float(np.median([item[7] - item[5] for item in train]))
                    test = by_id[hold["id"]]
                    errors = [item[7] - (item[5] + shift_y) for item in test]
                    med, within, worst = stats(errors)
                    steady_groups = []
                    for clip in steadies:
                        steady_groups.append([item[5] + shift_y for item in by_id[clip["id"]]])
                    spread, worst_spread = jitter(steady_groups)
                    base = {
                        "method": "glint",
                        "height": height,
                        "glint": glint,
                        "disk": disk,
                        "window": None,
                        "test": hold["id"],
                        "med": round(med, 2),
                        "within5": round(within, 1),
                        "worst": round(worst, 1),
                        "jitter": None if spread is None else round(spread, 2),
                        "jitter_worst": None if worst_spread is None else round(worst_spread, 1),
                        "shift": [round(shift_x, 2), round(shift_y, 2)],
                        "ms": round(per_frame, 2),
                        "fallback": 0,
                    }
                    rows.append(base)
                    print(line(base), flush=True)
                    radius_scale = height / NATIVE_H
                    for window in WINDOWS:
                        radius = window * radius_scale
                        errors = []
                        spreads = []
                        fallbacks = 0
                        counted = 0
                        started = time.perf_counter()
                        sequence = [hold] + steadies
                        for clip in sequence:
                            last_y = None
                            best_score = None
                            ys = []
                            for item in by_id[clip["id"]]:
                                response = item[0]
                                height_px = response.shape[0]
                                if last_y is None:
                                    sx, sy, score = item[1], item[2], item[3]
                                else:
                                    sx, sy, score = peak_at(response, last_y - radius, last_y + radius, margin)
                                    counted += 1
                                    if best_score is not None and score < WEAK * best_score:
                                        sx, sy, score = item[1], item[2], item[3]
                                        fallbacks += 1
                                best_score = score if best_score is None else max(best_score, score)
                                last_y = sy
                                _nx, ny = native_of(sx, sy, clip["frames"][len(ys)]["inverses"][height], clip["origin"], clip["scale"])
                                ny += shift_y
                                ys.append(ny)
                                if clip["id"] == hold["id"]:
                                    errors.append(item[7] - ny)
                            if clip["id"] != hold["id"]:
                                spreads.append(ys)
                        track_ms = (time.perf_counter() - started) * 1000 / max(1, len(errors))
                        med, within, worst = stats(errors)
                        spread, worst_spread = jitter(spreads)
                        row = {
                            "method": "glint-window",
                            "height": height,
                            "glint": glint,
                            "disk": disk,
                            "window": window,
                            "test": hold["id"],
                            "med": round(med, 2),
                            "within5": round(within, 1),
                            "worst": round(worst, 1),
                            "jitter": None if spread is None else round(spread, 2),
                            "jitter_worst": None if worst_spread is None else round(worst_spread, 1),
                            "shift": [round(shift_x, 2), round(shift_y, 2)],
                            "ms": round(per_frame + track_ms, 2),
                            "fallback": round(100.0 * fallbacks / max(1, counted), 1),
                        }
                        rows.append(row)
                        print(line(row), flush=True)
    return rows


def line(row):
    window = "-" if row["window"] is None else str(row["window"])
    glint = "-" if row.get("glint") is None else str(row["glint"])
    disk = "-" if row.get("disk") is None else str(row["disk"])
    win = "-" if row.get("hog") is None else str(row["hog"])
    test = row["test"].split("_")[-1] if False else row["test"][-15:]
    return (
        f"{row['method']:12} h {row['height']:4} g {glint:4} d {disk:4} "
        f"w {window:4} hog {win:3} {test:15} "
        f"med {row['med']:7.2f}  <=5 {row['within5']:5.1f}%  worst {row['worst']:7.1f}  "
        f"jitter {row['jitter']}  fb {row['fallback']}"
    )


def make_hog(win):
    return cv2.HOGDescriptor((win, win), (16, 16), (8, 8), (8, 8), 9)


def describe(hog, image):
    values = hog.compute(image)
    return np.asarray(values, np.float32).reshape(-1)


def patch_at(image, cx, cy, win):
    return cv2.getRectSubPix(image, (win, win), (float(cx), float(cy)))


def origins_of(width, height, y0, y1, win):
    found = []
    top0 = max(0, int(y0))
    top1 = min(height - win, int(y1))
    for top in range(top0, top1 + 1, STRIDE):
        cy = top + win / 2
        left = width * BORE[0]
        right = width * BORE[1]
        x0 = max(0, int(np.floor(left - win / 2)))
        x1 = min(width - win, int(np.floor(right - win / 2)))
        for left_x in range(x0, x1 + 1, STRIDE):
            found.append((left_x, top))
    return found


def features_at(hog, strip, origins):
    if not origins:
        return np.empty((0, hog.getDescriptorSize()), np.float32)
    points = [tuple(map(int, origin)) for origin in origins]
    values = hog.compute(strip, (STRIDE, STRIDE), (0, 0), points)
    feat = hog.getDescriptorSize()
    return np.asarray(values, np.float32).reshape(-1, feat)


def decision(svm, sign, feats):
    if len(feats) == 0:
        return np.empty(0, np.float32)
    raw = svm.predict(np.ascontiguousarray(feats), flags=cv2.ml.STAT_MODEL_RAW_OUTPUT)[1].ravel()
    return raw * sign


def fit_svm(pos, neg):
    samples = np.vstack(pos + neg).astype(np.float32)
    labels = np.array([1] * len(pos) + [-1] * len(neg), np.int32)
    svm = cv2.ml.SVM_create()
    svm.setType(cv2.ml.SVM_C_SVC)
    svm.setKernel(cv2.ml.SVM_LINEAR)
    svm.setC(0.05)
    svm.setTermCriteria((cv2.TERM_CRITERIA_MAX_ITER + cv2.TERM_CRITERIA_EPS, 800, 1e-4))
    svm.train(samples, cv2.ml.ROW_SAMPLE, labels)
    raw = svm.predict(samples[: len(pos)], flags=cv2.ml.STAT_MODEL_RAW_OUTPUT)[1].ravel()
    sign = 1.0 if float(np.mean(raw)) > 0 else -1.0
    margin = float(np.min(raw) * sign) * 0.5
    return svm, sign, margin


def search_hog(hog, svm, sign, strip, y0, y1, win):
    height, width = strip.shape[:2]
    found = origins_of(width, height, y0, y1, win)
    scores = decision(svm, sign, features_at(hog, strip, found))
    if len(scores) == 0:
        return width / 2, (y0 + y1) / 2, -1e9
    best = int(np.argmax(scores))
    left, top = found[best]
    cx, cy, coarse = left + win / 2, top + win / 2, float(scores[best])
    best_x, best_y, best_score = cx, cy, coarse
    for dy in range(-STRIDE, STRIDE + 1, 2):
        for dx in range(-4, 5, 2):
            x = cx + dx
            y = cy + dy
            if not (win / 2 <= x < width - win / 2 and win / 2 <= y < height - win / 2):
                continue
            score = float(decision(svm, sign, describe(hog, patch_at(strip, x, y, win)).reshape(1, -1))[0])
            if score > best_score:
                best_x, best_y, best_score = x, y, score
    return best_x, best_y, best_score


def train_hog(hog, samples, win):
    pos, neg = [], []
    prepared = []
    for strip, center in samples:
        prepared.append((strip, center))
        for dy in (-8, -4, 0, 4, 8):
            for dx in (-4, 0, 4):
                cx, cy = center[0] + dx, center[1] + dy
                if win / 2 <= cx < strip.shape[1] - win / 2 and win / 2 <= cy < strip.shape[0] - win / 2:
                    pos.append(describe(hog, patch_at(strip, cx, cy, win)))
        found = origins_of(strip.shape[1], strip.shape[0], 0, strip.shape[0] - win, win)
        far = []
        for left, top in found:
            if abs(top + win / 2 - center[1]) > win * 1.2 or abs(left + win / 2 - center[0]) > win * 1.2:
                far.append((left, top))
        step = max(1, len(far) // 20)
        for left, top in far[::step]:
            neg.append(describe(hog, patch_at(strip, left + win / 2, top + win / 2, win)))
    svm, sign, margin = fit_svm(pos, neg)
    mined = []
    for strip, center in prepared:
        found = origins_of(strip.shape[1], strip.shape[0], 0, strip.shape[0] - win, win)
        far = [(left, top) for left, top in found if abs(top + win / 2 - center[1]) > win or abs(left + win / 2 - center[0]) > win]
        if not far:
            continue
        scores = decision(svm, sign, features_at(hog, strip, far))
        order = np.argsort(scores)[::-1]
        taken = 0
        for pick in order:
            if scores[pick] <= 0 or taken >= 6:
                break
            left, top = far[int(pick)]
            mined.append(describe(hog, patch_at(strip, left + win / 2, top + win / 2, win)))
            taken += 1
            if len(mined) >= 500:
                break
        if len(mined) >= 500:
            break
    if mined:
        svm, sign, margin = fit_svm(pos, neg + mined)
    return svm, sign, margin


def center_on_strip(frame, clip, height):
    ix, iy = native_point_to_image(frame["lx"], frame["ly"], clip["origin"], clip["scale"])
    point = np.array([[[ix, iy]]], np.float32)
    mapped = cv2.perspectiveTransform(point, frame["forwards"][height])[0, 0]
    return float(mapped[0]), float(mapped[1])


def hog_passes(clips):
    rows = []
    sweeps = [clip for clip in clips if clip["kind"] == "sweep"]
    steadies = [clip for clip in clips if clip["kind"] == "steady"]
    height = 972
    for win in WINS:
        hog = make_hog(win)
        print(f"hog win {win} feat {hog.getDescriptorSize()}", flush=True)
        for hold in sweeps:
            train_clips = [clip for clip in sweeps if clip["id"] != hold["id"]] + steadies
            samples = []
            for clip in train_clips:
                for frame in clip["frames"]:
                    samples.append((frame["strips"][height], center_on_strip(frame, clip, height)))
            started = time.perf_counter()
            svm, sign, margin = train_hog(hog, samples, win)
            print(f"  trained on {len(samples)} frames in {time.perf_counter() - started:.1f}s  margin {margin:.2f}", flush=True)
            for window in WINDOWS:
                radius = window * height / NATIVE_H
                errors = []
                spreads = []
                fallbacks = 0
                counted = 0
                times = []
                for clip in [hold] + steadies:
                    last_y = None
                    ys = []
                    for frame in clip["frames"]:
                        strip = frame["strips"][height]
                        started = time.perf_counter()
                        full = last_y is None
                        if not full:
                            sx, sy, score = search_hog(hog, svm, sign, strip, last_y - radius, last_y + radius, win)
                            counted += 1
                            if score < margin:
                                full = True
                                fallbacks += 1
                        if full:
                            sx, sy, score = search_hog(hog, svm, sign, strip, 0, strip.shape[0] - win, win)
                        times.append(time.perf_counter() - started)
                        last_y = sy
                        _nx, ny = native_of(sx, sy, frame["inverses"][height], clip["origin"], clip["scale"])
                        ys.append(ny)
                        if clip["id"] == hold["id"]:
                            errors.append(frame["ly"] - ny)
                    if clip["id"] != hold["id"]:
                        spreads.append(ys)
                med, within, worst = stats(errors)
                spread, worst_spread = jitter(spreads)
                row = {
                    "method": "hog-window",
                    "height": height,
                    "glint": None,
                    "disk": None,
                    "window": window,
                    "hog": win,
                    "test": hold["id"],
                    "med": round(med, 2),
                    "within5": round(within, 1),
                    "worst": round(worst, 1),
                    "jitter": None if spread is None else round(spread, 2),
                    "jitter_worst": None if worst_spread is None else round(worst_spread, 1),
                    "shift": None,
                    "ms": round(float(np.median(times)) * 1000, 2),
                    "fallback": round(100.0 * fallbacks / max(1, counted), 1),
                }
                rows.append(row)
                print(line(row), flush=True)
    return rows


def sanity(clips):
    clip = next(item for item in clips if item["kind"] == "sweep")
    kernel = glint_kernel(972, 3.5, 28)
    margin = kernel.shape[0] // 2
    errors = []
    for frame in clip["frames"]:
        response = response_of(frame["strips"][972], kernel)
        sx, sy, _score = peak_at(response, 0, frame["strips"][972].shape[0], margin)
        _nx, ny = native_of(sx, sy, frame["inverses"][972], clip["origin"], clip["scale"])
        errors.append(abs(ny - frame["ly"]))
    med = float(np.median(errors))
    print(f"sanity {clip['id']} full-bore glint median |dy| {med:.0f} before the shift", flush=True)
    if med > 200:
        raise SystemExit("glint is nowhere near the clicks; coordinates are wrong")


def paired(rows):
    groups = {}
    for row in rows:
        key = (row["method"], row["height"], row.get("glint"), row.get("disk"), row.get("window"), row.get("hog"))
        groups.setdefault(key, []).append(row)
    summary = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        worse = max(items, key=lambda item: item["med"])
        summary.append((worse["med"], min(item["within5"] for item in items), items))
    summary.sort(key=lambda item: (item[0], -item[1]))
    return summary


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="cam-ui/recordings")
    parser.add_argument("--bbox", default="cam-ui/bbox.json")
    parser.add_argument("--out", default="eval/clip_search.json")
    parser.add_argument("--part", choices=("all", "glint", "hog"), default="all")
    args = parser.parse_args()
    cv2.setNumThreads(1)
    bbox = load_json(Path(args.bbox))
    heights = (972,) if args.part == "hog" else HEIGHTS
    print("loading", flush=True)
    clips = load_frames(args.root, bbox, heights)
    for clip in clips:
        print(f"  {clip['id']} {clip['kind']} {len(clip['frames'])} labeled", flush=True)
    if args.part != "hog":
        sanity(clips)
    rows = []
    if args.part in ("all", "glint"):
        rows.extend(glint_passes(clips))
    if args.part in ("all", "hog"):
        rows.extend(hog_passes(clips))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2))
    print("\nbest worse-sweep median |dy|", flush=True)
    for med, within, items in paired(rows)[:12]:
        sample = items[0]
        print(
            f"  worse {med:7.2f}  min<=5 {within:5.1f}%  {sample['method']} "
            f"h {sample['height']} g {sample.get('glint')} d {sample.get('disk')} "
            f"w {sample.get('window')} hog {sample.get('hog')}",
            flush=True,
        )


if __name__ == "__main__":
    main()
