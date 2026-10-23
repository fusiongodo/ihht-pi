"""Throwaway viewfinder. Latest JPEG on :8080/frame, native JPEG on :8080/snap.

The browser measures the float, so this process only captures. The stream size
is one of three presets: 640x480 at 8 fps, 1296x972 at 5 fps, or the native
2592x1944 at 2 fps. Stills stay at the OV5647 native size. One process owns the camera.
GET /focus returns a sharpness score. POST /bbox stores the tube corners.
POST /video switches the stream preset. POST /record saves lossless grayscale frames.
"""
import io
import json
import re
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Queue
from threading import Condition, Lock, Thread

import numpy as np
from PIL import Image
from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
from picamera2.request import MappedArray

NATIVE_SIZE = (2592, 1944)
PRESETS = {
    "640": ((640, 480), 8),
    "1296": ((1296, 972), 5),
    "2592": ((2592, 1944), 2),
}
RECORD_PRESETS = {"1296", "2592"}
CONTROLS = {
    "AeEnable": False,
    "ExposureTime": 20000,
    "AnalogueGain": 2.0,
    "AwbEnable": False,
    "ColourGains": (1.5, 1.5),
}
CROP_X = (1000, 1950)

camera_lock = Lock()
corners_lock = Lock()
record_lock = Lock()
native_corners = None
current_preset = "1296"
record_state = {"active": None, "done": 0, "total": 0, "last": None}
bbox_path = Path.home() / "ihht-bbox.json"
recordings_root = Path.home() / "recordings"
clip_id_re = re.compile(r"^[\w.-]+$")
record_file_re = re.compile(r"^(?:\d{3}\.png|clip\.json)$")
picam2 = Picamera2()
video_config = None
still_config = picam2.create_still_configuration(
    main={"size": NATIVE_SIZE, "format": "RGB888"},
    buffer_count=2,
)


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.score = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = bytes(buf)
            self.condition.notify_all()
        return len(buf)


stream = StreamingOutput()


def focus_score(jpeg):
    image = Image.open(io.BytesIO(jpeg)).convert("L")
    image.thumbnail((160, 120))
    width, height = image.size
    left, top = width // 4, height // 4
    image = image.crop((left, top, left + width // 2, top + height // 2))
    pixels = np.asarray(image, dtype=np.int16)
    horizontal = np.abs(pixels[:, 1:] - pixels[:, :-1]).mean()
    vertical = np.abs(pixels[1:, :] - pixels[:-1, :]).mean()
    return round(float(horizontal + vertical), 1)


def load_corners(payload):
    corners = payload["corners"]
    if (
        not isinstance(corners, list)
        or len(corners) != 4
        or any(
            not isinstance(point, list)
            or len(point) != 2
            or not all(isinstance(value, (int, float)) for value in point)
            or point[0] < 0
            or point[0] > NATIVE_SIZE[0]
            or point[1] < 0
            or point[1] > NATIVE_SIZE[1]
            for point in corners
        )
    ):
        raise ValueError("need four corners inside the frame")
    return [[float(point[0]), float(point[1])] for point in corners]


def read_saved_corners():
    if not bbox_path.is_file():
        return None
    return load_corners(json.loads(bbox_path.read_text()))


def make_video(name):
    size, fps = PRESETS[name]
    return picam2.create_video_configuration(
        main={"size": size, "format": "YUV420"},
        controls={"FrameRate": fps},
        buffer_count=2,
    )


def start_encoder():
    picam2.set_controls(CONTROLS)
    picam2.start_recording(JpegEncoder(num_threads=2, q=70), FileOutput(stream))


def apply_preset(name):
    global video_config, current_preset
    if name not in PRESETS:
        raise ValueError("unknown preset")
    with record_lock:
        if record_state["active"]:
            raise RuntimeError("recording")
        with camera_lock:
            picam2.stop_recording()
            video_config = make_video(name)
            picam2.configure(video_config)
            start_encoder()
            current_preset = name


def video_status():
    size, fps = PRESETS[current_preset]
    return {"preset": current_preset, "width": size[0], "height": size[1], "fps": fps}


def frame_crop(width, height):
    x0 = CROP_X[0] * width // NATIVE_SIZE[0]
    x1 = CROP_X[1] * width // NATIVE_SIZE[0]
    return [x0, 0, x1, height]


def scale_token(scale):
    value = float(scale)
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def clean_scale(scale):
    if scale is None:
        return None
    if isinstance(scale, bool) or not isinstance(scale, (int, float)):
        raise ValueError("scale must be a number")
    value = float(scale)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("scale must be a number")
    if value == int(value):
        return int(value)
    return value


def new_clip_id(kind, scale):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = "" if scale is None else f"_{scale_token(scale)}"
    base = f"{stamp}_{kind}{suffix}"
    clip_id = base
    number = 2
    while (recordings_root / clip_id).exists():
        clip_id = f"{base}-{number}"
        number += 1
    return clip_id


def frame_stamp(origin, timestamp, mono_origin):
    if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
        if origin[0] is None:
            origin[0] = float(timestamp)
            return 0.0
        return round((float(timestamp) - origin[0]) / 1e9, 6)
    return round(time.monotonic() - mono_origin, 6)


def record_frames(clip_id, kind, scale, count, preset):
    width, height = PRESETS[preset][0]
    fps = PRESETS[preset][1]
    crop = frame_crop(width, height)
    x0, x1 = crop[0], crop[2]
    directory = recordings_root / clip_id
    saved = {}
    jobs = Queue()
    gate = {"stop": False, "n": 0}
    grab_lock = Lock()

    def on_frame(request):
        with grab_lock:
            if gate["stop"] or gate["n"] >= count:
                return
            try:
                with MappedArray(request, "main") as mapped:
                    array = mapped.array
                    if array.ndim != 2 or array.shape[0] < height or array.shape[1] < width:
                        raise RuntimeError(f"unexpected frame shape {array.shape}")
                    plane = array[:height, :width]
                    pixels = np.ascontiguousarray(plane[:, x0:x1], dtype=np.uint8)
                timestamp = request.get_metadata().get("SensorTimestamp")
            except Exception as exc:
                print(f"record grab {clip_id}: {exc}", flush=True)
                return
            index = gate["n"]
            gate["n"] = index + 1
            jobs.put((index, pixels, timestamp))

    def writer():
        origin = [None]
        mono_origin = time.monotonic()
        while True:
            item = jobs.get()
            if item is None:
                return
            index, pixels, timestamp = item
            try:
                name = f"{index:03d}.png"
                Image.fromarray(pixels, mode="L").save(
                    directory / name,
                    format="PNG",
                    compress_level=1,
                )
                saved[index] = {"file": name, "t": frame_stamp(origin, timestamp, mono_origin)}
                with record_lock:
                    if record_state["active"] == clip_id:
                        record_state["done"] = len(saved)
            except Exception as exc:
                print(f"record save {clip_id} {index}: {exc}", flush=True)

    try:
        directory.mkdir(parents=True, exist_ok=True)
        saver = Thread(target=writer, daemon=True)
        saver.start()
        picam2.post_callback = on_frame
        deadline = time.monotonic() + count + 10
        try:
            while gate["n"] < count and time.monotonic() < deadline:
                time.sleep(0.02)
        finally:
            with grab_lock:
                gate["stop"] = True
            if picam2.post_callback is on_frame:
                picam2.post_callback = None
            jobs.put(None)
            saver.join()
    except Exception as exc:
        print(f"record failed {clip_id}: {exc}", flush=True)
    frames = [saved[index] for index in range(count) if index in saved]
    payload = {
        "id": clip_id,
        "kind": kind,
        "scale": scale,
        "preset": preset,
        "frameWidth": width,
        "frameHeight": height,
        "crop": crop,
        "fps": fps,
        "frames": frames,
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "clip.json").write_text(json.dumps(payload, indent=2) + "\n")
    except Exception as exc:
        print(f"record meta failed {clip_id}: {exc}", flush=True)
    with record_lock:
        record_state["active"] = None
        record_state["done"] = len(frames)
        record_state["total"] = count
        record_state["last"] = clip_id
    if len(frames) >= 2 and frames[-1]["t"] > frames[0]["t"]:
        span = frames[-1]["t"] - frames[0]["t"]
        rate = (len(frames) - 1) / span
        print(f"record {clip_id} {len(frames)}/{count} in {span:.3f}s ({rate:.2f} fps)", flush=True)
    else:
        print(f"record {clip_id} {len(frames)}/{count}", flush=True)


def score_loop():
    while True:
        with stream.condition:
            stream.condition.wait()
            frame = stream.frame
        if not frame:
            continue
        try:
            stream.score = focus_score(frame)
        except Exception:
            pass


def start_preview():
    wanted = tuple(video_config["main"]["size"])
    size = tuple(picam2.camera_config["main"]["size"])
    if size != wanted:
        picam2.switch_mode(video_config)
    start_encoder()


def snap_jpeg():
    with camera_lock:
        picam2.stop_recording()
        buf = io.BytesIO()
        try:
            picam2.set_controls(CONTROLS)
            picam2.switch_mode_and_capture_file(still_config, buf, format="jpeg")
            return buf.getvalue()
        finally:
            start_preview()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/stream":
            self._stream()
        elif path == "/frame":
            self._frame()
        elif path == "/snap":
            self._snap()
        elif path == "/focus":
            self._focus()
        elif path == "/video":
            self._json(video_status())
        elif path == "/record":
            self._record_status()
        elif path.startswith("/recordings/"):
            self._serve_recording(path)
        else:
            self.send_error(404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400)
            return
        if path == "/bbox":
            self._save_bbox(body)
        elif path == "/video":
            self._set_video(body)
        elif path == "/record":
            self._start_record(body)
        else:
            self.send_error(404)

    def _save_bbox(self, body):
        global native_corners
        try:
            corners = load_corners(body)
        except (KeyError, ValueError, TypeError):
            self.send_error(400)
            return
        with corners_lock:
            native_corners = corners
            bbox_path.write_text(
                json.dumps({"width": NATIVE_SIZE[0], "height": NATIVE_SIZE[1], "corners": corners})
            )
        self.send_response(204)
        self.end_headers()

    def _set_video(self, body):
        try:
            apply_preset(body.get("preset"))
        except RuntimeError as exc:
            status = 409 if str(exc) == "recording" else 500
            self._json({"error": str(exc)}, status=status)
            return
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)
            return
        self._json(video_status())

    def _start_record(self, body):
        try:
            count = body["frames"]
            kind = body["kind"]
            scale = clean_scale(body.get("scale", None))
        except (KeyError, TypeError, ValueError) as exc:
            self._json({"error": str(exc) or "need frames and kind"}, status=400)
            return
        if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > 999:
            self._json({"error": "frames must be an integer from 1 to 999"}, status=400)
            return
        if kind not in ("steady", "sweep"):
            self._json({"error": "kind must be steady or sweep"}, status=400)
            return
        with record_lock:
            if record_state["active"]:
                self._json({"error": "recording"}, status=409)
                return
            preset = current_preset
            if preset not in RECORD_PRESETS:
                self._json({"error": "preset must be 1296 or 2592"}, status=409)
                return
            clip_id = new_clip_id(kind, scale)
            record_state["active"] = clip_id
            record_state["done"] = 0
            record_state["total"] = count
        Thread(
            target=record_frames,
            args=(clip_id, kind, scale, count, preset),
            daemon=True,
        ).start()
        self._json({"id": clip_id, "frames": count}, status=202)

    def _record_status(self):
        with record_lock:
            payload = {
                "active": record_state["active"],
                "done": record_state["done"],
                "total": record_state["total"],
                "last": record_state["last"],
            }
        self._json(payload)

    def _serve_recording(self, path):
        parts = path.split("/")
        if len(parts) != 4 or parts[1] != "recordings":
            self.send_error(404)
            return
        clip_id, name = parts[2], parts[3]
        if (
            not clip_id_re.fullmatch(clip_id)
            or clip_id in (".", "..")
            or not record_file_re.fullmatch(name)
        ):
            self.send_error(404)
            return
        root = recordings_root.resolve()
        directory = (root / clip_id).resolve()
        if directory.parent != root:
            self.send_error(404)
            return
        target = directory / name
        try:
            data = target.read_bytes()
        except OSError:
            self.send_error(404)
            return
        content_type = "image/png" if name.endswith(".png") else "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _stream(self):
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
        self.end_headers()
        try:
            while True:
                with stream.condition:
                    stream.condition.wait()
                    frame = stream.frame
                self.wfile.write(b"--FRAME\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _frame(self):
        frame = stream.frame
        if not frame:
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(frame)))
        self.end_headers()
        self.wfile.write(frame)

    def _snap(self):
        with record_lock:
            if record_state["active"]:
                self._json({"error": "recording"}, status=409)
                return
            jpeg = snap_jpeg()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg)))
        self.end_headers()
        self.wfile.write(jpeg)

    def _focus(self):
        self._json({"score": stream.score})

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        path = self.path.split("?", 1)[0]
        if path in ("/stream", "/focus", "/frame") or (path == "/record" and self.command == "GET"):
            return
        super().log_message(fmt, *args)


def main():
    global native_corners, video_config
    try:
        native_corners = read_saved_corners()
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
        native_corners = None
    video_config = make_video(current_preset)
    picam2.configure(video_config)
    start_encoder()
    Thread(target=score_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    print("listening on 0.0.0.0:8080", flush=True)
    try:
        server.serve_forever()
    finally:
        picam2.stop_recording()
        picam2.stop()


if __name__ == "__main__":
    main()
