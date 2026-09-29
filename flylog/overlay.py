"""Video overlay: flight telemetry rendered as a transparent video, to put over your footage.

    flylog overlay vol.igc incrustation.mov --video GX010123.MP4     # synced on the clip
    flylog overlay vol.igc incrustation.mov --start 12:41:00 --duration 90

The .mov output is ProRes 4444 with alpha (Premiere, DaVinci Resolve, Final Cut);
.webm is VP9 with alpha. Requires ffmpeg and Pillow (pip install "flylog[plot]").
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .geo import LocalProjection
from .metrics import load_factor, turn_rates
from .parser import Flight, read_igc
from .stats import ground_speed, vario

CLIMB = (74, 222, 128)
SINK = (248, 113, 113)
WHITE = (255, 255, 255)
PANEL = (10, 14, 24, 150)
ACCENT = (56, 189, 248)


@dataclass
class Telemetry:
    """Flight data resampled at any instant (linear interpolation between fixes)."""

    t0: datetime
    t: list[float]
    x: list[float]
    y: list[float]
    alt: list[float]
    vario: list[float]
    speed: list[float]
    g: list[float]

    @classmethod
    def from_flight(cls, flight: Flight) -> Telemetry:
        fixes = [f for f in flight.fixes if f.valid]
        if len(fixes) < 2:
            raise ValueError("Pas assez de points GPS valides.")
        proj = LocalProjection(fixes[0].lat, fixes[0].lon)
        xy = [proj.to_xy(f.lat, f.lon) for f in fixes]
        speed = ground_speed(fixes, 5)
        return cls(
            t0=fixes[0].time,
            t=[(f.time - fixes[0].time).total_seconds() for f in fixes],
            x=[p[0] for p in xy],
            y=[p[1] for p in xy],
            alt=[float(f.alt) for f in fixes],
            vario=vario(fixes, 5),
            speed=speed,
            g=[load_factor(s / 3.6, r) for s, r in zip(speed, turn_rates(fixes, 5))],
        )

    def at(self, seconds: float) -> dict[str, float]:
        i = min(max(bisect.bisect_right(self.t, seconds) - 1, 0), len(self.t) - 2)
        span = self.t[i + 1] - self.t[i]
        k = min(max((seconds - self.t[i]) / span if span else 0, 0), 1)
        lerp = lambda arr: arr[i] + (arr[i + 1] - arr[i]) * k  # noqa: E731
        return {name: lerp(getattr(self, name)) for name in ("x", "y", "alt", "vario", "speed", "g")} | {"i": i}


def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    try:  # DejaVu ships with matplotlib, so it is always there with the [plot] extra
        import matplotlib

        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        return ImageFont.truetype(str(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name), size)
    except Exception:
        return ImageFont.load_default(size=size)


class OverlayRenderer:
    def __init__(self, tel: Telemetry, width: int = 1920, height: int = 1080,
                 utc: bool = False):
        from PIL import Image, ImageDraw

        self.tel, self.w, self.h, self.utc = tel, width, height, utc
        s = self.s = height / 1080
        self.big, self.mid, self.small = _font(int(64 * s), True), _font(int(30 * s), True), _font(int(20 * s))

        # Mini-map: whole track drawn once.
        self.map_size = int(300 * s)
        self.map_pos = (width - self.map_size - int(40 * s), height - self.map_size - int(40 * s))
        xs, ys = tel.x, tel.y
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1)
        pad = 18 * s
        scale = (self.map_size - 2 * pad) / span
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        self.map_pt = lambda x, y: (self.map_size / 2 + (x - cx) * scale,  # noqa: E731
                                    self.map_size / 2 - (y - cy) * scale)
        self.map_track = [self.map_pt(x, y) for x, y in zip(xs, ys)]
        self.map_base = Image.new("RGBA", (self.map_size,) * 2, (0, 0, 0, 0))
        d = ImageDraw.Draw(self.map_base)
        d.rounded_rectangle((0, 0, self.map_size - 1, self.map_size - 1), radius=int(18 * s), fill=PANEL)
        d.line(self.map_track, fill=(255, 255, 255, 110), width=max(1, int(2 * s)))

        # Altitude profile strip, drawn once.
        self.prof_box = (int(40 * s), height - int(120 * s), self.map_pos[0] - int(30 * s), height - int(40 * s))
        x0, y0, x1, y1 = self.prof_box
        lo, hi = min(tel.alt), max(tel.alt)
        self.prof_x = lambda t: x0 + (x1 - x0) * t / (tel.t[-1] or 1)  # noqa: E731
        self.prof_y = lambda a: y1 - (y1 - y0) * (a - lo) / ((hi - lo) or 1)  # noqa: E731
        self.prof_base = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(self.prof_base)
        d.rounded_rectangle((x0 - 14 * s, y0 - 14 * s, x1 + 14 * s, y1 + 14 * s), radius=int(16 * s), fill=PANEL)
        step = max(1, len(tel.t) // 1500)
        pts = [(self.prof_x(tel.t[i]), self.prof_y(tel.alt[i])) for i in range(0, len(tel.t), step)]
        d.polygon(pts + [(pts[-1][0], y1), (pts[0][0], y1)], fill=(56, 189, 248, 70))
        d.line(pts, fill=ACCENT + (230,), width=max(1, int(2 * s)))

    def frame(self, seconds: float):
        from PIL import ImageDraw

        s, tel = self.s, self.tel
        v = tel.at(seconds)
        img = self.prof_base.copy()
        d = ImageDraw.Draw(img)

        # Profile cursor.
        px, py = self.prof_x(seconds), self.prof_y(v["alt"])
        d.line((px, self.prof_box[1] - 6 * s, px, self.prof_box[3] + 6 * s), fill=WHITE + (200,), width=max(1, int(2 * s)))
        d.ellipse((px - 7 * s, py - 7 * s, px + 7 * s, py + 7 * s), fill=WHITE, outline=ACCENT, width=max(1, int(3 * s)))

        # Telemetry panel, above the profile.
        x, y = int(40 * s), self.prof_box[1] - int(230 * s)
        d.rounded_rectangle((x, y, x + int(420 * s), y + int(190 * s)), radius=int(18 * s), fill=PANEL)
        vz = v["vario"]
        color = CLIMB if vz > 0.2 else SINK if vz < -1.5 else WHITE
        d.text((x + 24 * s, y + 14 * s), f"{vz:+.1f}", font=self.big, fill=color)
        d.text((x + 230 * s, y + 52 * s), "m/s", font=self.mid, fill=color)
        # Vario gauge (±5 m/s).
        gx, gy0, gy1 = x + int(390 * s), y + int(20 * s), y + int(170 * s)
        mid = (gy0 + gy1) / 2
        d.rounded_rectangle((gx - 6 * s, gy0, gx + 6 * s, gy1), radius=int(6 * s), fill=(255, 255, 255, 50))
        level = mid - max(-5, min(5, vz)) / 5 * (gy1 - gy0) / 2
        d.rounded_rectangle((gx - 6 * s, min(mid, level), gx + 6 * s, max(mid, level)), radius=int(6 * s), fill=color)

        when = tel.t0 + timedelta(seconds=seconds)
        when = when if self.utc else when.replace(tzinfo=timezone.utc).astimezone()
        line = f"{v['alt']:.0f} m   {v['speed']:.0f} km/h"
        d.text((x + 24 * s, y + 100 * s), line, font=self.mid, fill=WHITE)
        extra = f"{when:%H:%M:%S}" + (" UTC" if self.utc else "")
        if v["g"] >= 1.3:
            extra += f"    {v['g']:.1f} G"
        d.text((x + 24 * s, y + 146 * s), extra, font=self.small, fill=(255, 255, 255, 200))

        # Mini-map with flown part and position.
        mm = self.map_base.copy()
        md = ImageDraw.Draw(mm)
        flown = self.map_track[: v["i"] + 1] + [self.map_pt(v["x"], v["y"])]
        if len(flown) > 1:
            md.line(flown, fill=ACCENT + (255,), width=max(2, int(3 * s)))
        mx, my = flown[-1]
        md.ellipse((mx - 8 * s, my - 8 * s, mx + 8 * s, my + 8 * s), fill=WHITE, outline=ACCENT, width=max(1, int(3 * s)))
        img.alpha_composite(mm, self.map_pos)
        return img


def _probe(video: Path) -> tuple[datetime, float]:
    """Recording start (UTC) and duration of a video, from its metadata."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags=creation_time",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    fmt = json.loads(out.stdout)["format"]
    created = fmt.get("tags", {}).get("creation_time")
    if not created:
        raise ValueError("La vidéo n'indique pas son heure de tournage : utilise --start.")
    start = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(timezone.utc)
    return start.replace(tzinfo=None), float(fmt["duration"])


def _parse_start(text: str, flight_start: datetime) -> datetime:
    """HH:MM[:SS] in local time (or UTC with --utc handled by caller) on the flight day."""
    parts = [int(p) for p in text.split(":")]
    h, m, sec = (parts + [0, 0])[:3]
    return flight_start.replace(hour=h, minute=m, second=sec, microsecond=0)


def render_overlay(flight: Flight, out: str | Path, start: datetime, duration: float,
                   fps: int = 30, size: tuple[int, int] = (1920, 1080), utc: bool = False,
                   progress=None) -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg est introuvable : installe-le (https://ffmpeg.org).")
    out = Path(out)
    codec = {
        ".mov": ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le"],
        ".webm": ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "2M"],
    }.get(out.suffix.lower())
    if codec is None:
        raise ValueError("Format de sortie : .mov (ProRes 4444) ou .webm (VP9), pour garder la transparence.")

    tel = Telemetry.from_flight(flight)
    offset = (start - tel.t0).total_seconds()
    if offset + duration < 0 or offset > tel.t[-1]:
        end = tel.t0 + timedelta(seconds=tel.t[-1])
        raise ValueError(f"Ce moment n'est pas dans le vol (vol de {tel.t0:%H:%M:%S} à {end:%H:%M:%S} UTC).")

    renderer = OverlayRenderer(tel, *size, utc=utc)
    w, h = size
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
         "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", *codec, str(out)],
        stdin=subprocess.PIPE,
    )
    frames = max(1, round(duration * fps))
    assert proc.stdin
    for n in range(frames):
        proc.stdin.write(renderer.frame(offset + n / fps).tobytes())
        if progress and n % fps == 0:
            progress(n, frames)
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg a échoué pendant l'encodage.")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="flylog overlay",
        description="Génère une incrustation vidéo transparente (vario, altitude, vitesse, "
                    "mini-carte, profil) à poser sur tes images de vol.",
    )
    ap.add_argument("igc", help="trace du vol (.igc)")
    ap.add_argument("sortie", help="vidéo à créer : .mov (ProRes 4444) ou .webm")
    ap.add_argument("--video", help="clip à synchroniser : heure de début et durée lues dans ses métadonnées")
    ap.add_argument("--start", help="heure de début HH:MM[:SS] (heure locale, UTC avec --utc)")
    ap.add_argument("--duration", type=float, help="durée en secondes (défaut : 60, ou celle du clip)")
    ap.add_argument("--offset", type=float, default=0,
                    help="décalage en secondes si l'horloge de la caméra n'est pas à l'heure")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--size", default="1920x1080", help="taille, par ex. 3840x2160")
    ap.add_argument("--utc", action="store_true", help="heures en UTC plutôt qu'en heure locale")
    args = ap.parse_args(argv)

    flight = read_igc(args.igc)
    try:
        tel_start = next(f.time for f in flight.fixes if f.valid)
        if args.video:
            start, duration = _probe(Path(args.video))
        elif args.start:
            start = _parse_start(args.start, tel_start)
            if not args.utc:  # given in local time: convert to UTC like the IGC
                start = start.astimezone(timezone.utc).replace(tzinfo=None)
            duration = 60.0
        else:
            ap.error("indique --video CLIP ou --start HH:MM:SS")
        duration = args.duration or duration
        start += timedelta(seconds=args.offset)
        w, h = (int(v) for v in args.size.lower().split("x"))

        print(f"  Début {start:%H:%M:%S} UTC, {duration:.0f} s à {args.fps} i/s → {args.sortie}")
        render_overlay(flight, args.sortie, start, duration, args.fps, (w, h), args.utc,
                       progress=lambda n, total: print(f"\r  {100 * n // total:3d} %", end="", flush=True))
        print(f"\r  Incrustation enregistrée : {args.sortie}")
    except (ValueError, RuntimeError, StopIteration, subprocess.CalledProcessError) as e:
        print(f"\nErreur : {e}", file=sys.stderr)
        return 1
    return 0
