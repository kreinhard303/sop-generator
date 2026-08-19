"""Periodic screenshot extraction from a video file, via ffmpeg."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Frame:
    timestamp_s: int
    path: Path


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install it (e.g. `winget install ffmpeg`) "
            "and re-run."
        )


def extract_frames(
    video_path: Path,
    out_dir: Path,
    interval_s: int = 15,
    *,
    crop_left_fraction: float = 0.0,
    crop_right_fraction: float = 0.0,
    crop_top_fraction: float = 0.0,
    crop_bottom_fraction: float = 0.0,
    sharpen: bool = True,
) -> list[Frame]:
    """Extract one JPEG every `interval_s` seconds into `out_dir`.

    `crop_left_fraction` trims the black margin the shared browser window
    leaves on the left (the window isn't flush with the screen edge — this
    is separate from and in addition to the sidebar/chrome/taskbar crops).
    `crop_right_fraction` trims Fathom's fixed-width participant sidebar
    plus the app's own scrollbar off the right edge. `crop_top_fraction`
    trims Fathom's black header bar plus the browser's own chrome
    (tabs/address/bookmarks bar) off the top, stopping right at the shared
    app's own UI. `crop_bottom_fraction` trims the black band below the
    taskbar at the bottom. All four are fractions of frame width/height,
    not pixel counts, so they hold up if Fathom's export resolution changes.
    """
    _require_ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "frame_%05d.jpg"

    filters = []
    if crop_left_fraction > 0 or crop_right_fraction > 0 or crop_top_fraction > 0 or crop_bottom_fraction > 0:
        horizontal_fraction = 1 - crop_left_fraction - crop_right_fraction
        vertical_fraction = 1 - crop_top_fraction - crop_bottom_fraction
        filters.append(
            f"crop=iw*{horizontal_fraction}:ih*{vertical_fraction}:"
            f"iw*{crop_left_fraction}:ih*{crop_top_fraction}"
        )
    filters.append(f"fps=1/{interval_s}")
    if sharpen:
        # Mild luma-only unsharp mask — these recordings are low-bitrate
        # (~500kb/s at 720p), so text benefits from a modest sharpen pass.
        filters.append("unsharp=5:5:0.8:5:5:0.0")

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vf", ",".join(filters),
        "-qscale:v", "2",
        str(pattern),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed:\n{result.stderr}")

    frames = []
    for i, frame_path in enumerate(sorted(out_dir.glob("frame_*.jpg"))):
        frames.append(Frame(timestamp_s=i * interval_s, path=frame_path))
    return frames
