"""Write click, shifted glint, and HOG marks for the sweep slideshow."""
import json
from pathlib import Path

import numpy as np

from search_clips import glint_kernel, load_frames, load_json, native_of, peak_at, response_of

HEIGHT = 972
GLINT = 2.5
DISK = 40


def glint_tracks(clips):
    sweeps = [clip for clip in clips if clip["kind"] == "sweep"]
    steadies = [clip for clip in clips if clip["kind"] == "steady"]
    kernel = glint_kernel(HEIGHT, GLINT, DISK)
    margin = kernel.shape[0] // 2
    located = {}
    for clip in clips:
        found = []
        for frame in clip["frames"]:
            strip = frame["strips"][HEIGHT]
            response = response_of(strip, kernel)
            sx, sy, _score = peak_at(response, 0, strip.shape[0], margin)
            x, y = native_of(sx, sy, frame["inverses"][HEIGHT], clip["origin"], clip["scale"])
            found.append((frame["file"], x, y, frame["lx"], frame["ly"]))
        located[clip["id"]] = found
    tracks = {}
    for hold in sweeps:
        train_ids = [clip["id"] for clip in sweeps if clip["id"] != hold["id"]]
        train_ids += [clip["id"] for clip in steadies]
        shift_x = float(np.median([label_x - x for clip_id in train_ids for _file, x, _y, label_x, _label_y in located[clip_id]]))
        shift_y = float(np.median([label_y - y for clip_id in train_ids for _file, _x, y, _label_x, label_y in located[clip_id]]))
        frames = {}
        for file, x, y, label_x, label_y in located[hold["id"]]:
            frames[file] = {
                "glint": [round(x + shift_x, 2), round(y + shift_y, 2)],
                "label": [label_x, label_y],
            }
        tracks[hold["id"]] = frames
    return tracks


def interval_of(clip_path):
    times = [float(frame["t"]) for frame in load_json(clip_path)["frames"] if "t" in frame]
    gaps = [b - a for a, b in zip(times, times[1:]) if b > a]
    if not gaps:
        return 0.4
    return float(np.median(gaps))


def main():
    root = Path("cam-ui/recordings")
    hog = load_json(Path("eval/hog_tracks.json"))
    bbox = load_json(Path("cam-ui/bbox.json"))
    clips = load_frames(root, bbox, (HEIGHT,))
    located = glint_tracks(clips)
    sweeps = []
    for clip_id in sorted(located):
        marks = located[clip_id]
        hog_clip = hog[clip_id]
        frames = []
        for frame in load_json(root / clip_id / "clip.json")["frames"]:
            file = frame["file"]
            mark = marks.get(file)
            point = hog_clip.get(file)
            if not mark or not point:
                continue
            frames.append(
                {
                    "file": file,
                    "click": mark["label"],
                    "glint": mark["glint"],
                    "hog": [point["x"], point["y"]],
                }
            )
        sweeps.append(
            {
                "id": clip_id,
                "interval": round(interval_of(root / clip_id / "clip.json"), 4),
                "frames": frames,
            }
        )
    out = Path("eval/playback.json")
    out.write_text(json.dumps({"sweeps": sweeps}))
    print(out, [(item["id"], len(item["frames"]), item["interval"]) for item in sweeps], flush=True)


if __name__ == "__main__":
    main()
