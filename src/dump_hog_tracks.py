"""Native positions of the best HOG tracker on both sweeps.

The model for a sweep is trained on the other sweep plus the steady clips.
"""
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from search_clips import (
    NATIVE_H,
    center_on_strip,
    load_frames,
    load_json,
    make_hog,
    native_of,
    search_hog,
    train_hog,
)

HEIGHT = 972
WIN = 32
WINDOW = 160


def main():
    root = Path(sys.argv[1])
    bbox = load_json(sys.argv[2])
    out = Path(sys.argv[3])
    cv2.setNumThreads(1)
    clips = load_frames(root, bbox, (HEIGHT,))
    sweeps = [clip for clip in clips if clip["kind"] == "sweep"]
    steadies = [clip for clip in clips if clip["kind"] == "steady"]
    hog = make_hog(WIN)
    radius = WINDOW * HEIGHT / NATIVE_H
    tracks = {}
    for hold in sweeps:
        train = [clip for clip in sweeps if clip["id"] != hold["id"]] + steadies
        samples = [
            (frame["strips"][HEIGHT], center_on_strip(frame, clip, HEIGHT))
            for clip in train
            for frame in clip["frames"]
        ]
        svm, sign, margin = train_hog(hog, samples, WIN)
        last = None
        frames = {}
        for frame in hold["frames"]:
            strip = frame["strips"][HEIGHT]
            full = last is None
            if not full:
                sx, sy, score = search_hog(hog, svm, sign, strip, last - radius, last + radius, WIN)
                if score < margin:
                    full = True
            if full:
                sx, sy, score = search_hog(hog, svm, sign, strip, 0, strip.shape[0] - WIN, WIN)
            last = sy
            x, y = native_of(sx, sy, frame["inverses"][HEIGHT], hold["origin"], hold["scale"])
            frames[frame["file"]] = {"x": round(x, 2), "y": round(y, 2)}
        tracks[hold["id"]] = frames
        print(hold["id"], len(frames), flush=True)
    out.write_text(json.dumps(tracks))
    print("wrote", out, flush=True)


if __name__ == "__main__":
    main()
