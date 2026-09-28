"""
core_processing.py

Core video-processing logic shared by the GUI. Handles:
  - probing source/splash/endboard clips
  - normalizing resolution/fps/audio across clips
  - building an ffmpeg command that concatenates: [splash] -> source -> [endboard]
  - applying an optional transition (crossfade to white / fade to black then
    white) to the TAIL of the source clip only, immediately before the
    endboard cut

This module has no GUI dependencies and can be imported/tested from a plain
Python shell or script.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

PRORES_PROFILES = {
    "proxy": "0",
    "lt": "1",
    "standard": "2",
    "hq": "3",
    "4444": "4",
}

TRANSITION_NONE = "none"
TRANSITION_CROSSFADE_WHITE = "crossfade_white"
TRANSITION_FADE_BLACK_WHITE = "fade_black_white"

TRANSITION_LABELS = {
    TRANSITION_NONE: "None",
    TRANSITION_CROSSFADE_WHITE: "Crossfade to white",
    TRANSITION_FADE_BLACK_WHITE: "Fade to black, then white",
}


def _bundled_dir() -> Path:
    """Folder to look for a bundled ffmpeg/ffprobe in, whether running as a
    plain script or as a PyInstaller-frozen app."""
    if getattr(sys, "frozen", False):
        # PyInstaller --onefile extracts to a temp dir at runtime (sys._MEIPASS);
        # --onedir instead keeps everything next to the executable.
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def resolve_binary(name: str) -> str:
    """
    Finds the ffmpeg/ffprobe binary to use, preferring one bundled alongside
    a packaged app (ffmpeg_bin/ffmpeg or ffmpeg_bin/ffmpeg.exe) over whatever
    is on the system PATH. This lets a packaged .exe/.app work on a machine
    with no separate ffmpeg install.
    """
    exe_name = f"{name}.exe" if sys.platform.startswith("win") else name
    bundled = _bundled_dir() / "ffmpeg_bin" / exe_name
    if bundled.exists():
        return str(bundled)
    found = shutil.which(name)
    return found if found else name  # fall back to bare name; subprocess will raise a clear error if missing


def probe(path: Path) -> dict:
    """Return basic stream info for a file via ffprobe."""
    cmd = [
        resolve_binary("ffprobe"), "-v", "error",
        "-print_format", "json",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}:\n{result.stderr}")
    data = json.loads(result.stdout)

    info = {"width": None, "height": None, "fps": None, "has_audio": False, "duration": None}
    for stream in data.get("streams", []):
        if stream["codec_type"] == "video" and info["width"] is None:
            info["width"] = stream["width"]
            info["height"] = stream["height"]
            num, _, den = stream["r_frame_rate"].partition("/")
            den = den or "1"
            info["fps"] = float(num) / float(den)
            info["duration"] = float(stream.get("duration", 0) or 0)
    for stream in data.get("streams", []):
        if stream["codec_type"] == "audio":
            info["has_audio"] = True
    if info["width"] is None:
        raise RuntimeError(f"No video stream found in {path}")
    if not info["duration"]:
        cmd2 = [resolve_binary("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
        r2 = subprocess.run(cmd2, capture_output=True, text=True)
        info["duration"] = float(r2.stdout.strip() or 0)
    return info


def build_transition_fragment(clip_duration: float, transition: str, transition_duration: float) -> str:
    """
    Returns an ffmpeg filter fragment (starting with a comma) to append to the
    source clip's video filter chain, applying the chosen transition to the
    tail of the clip. Returns "" if no transition is requested.
    Clamped so the transition never exceeds the clip's own duration.
    """
    if transition == TRANSITION_NONE or transition_duration <= 0:
        return ""

    d = min(transition_duration, max(clip_duration - 0.05, 0.05))
    start = max(clip_duration - d, 0.0)

    if transition == TRANSITION_CROSSFADE_WHITE:
        return f",fade=type=out:start_time={start:.3f}:duration={d:.3f}:color=white"

    if transition == TRANSITION_FADE_BLACK_WHITE:
        half = d / 2.0
        start2 = start + half
        return (
            f",fade=type=out:start_time={start:.3f}:duration={half:.3f}:color=black"
            f",fade=type=out:start_time={start2:.3f}:duration={half:.3f}:color=white"
        )

    raise ValueError(f"Unknown transition: {transition}")


def build_command(source: Path, output: Path, crf: str, preset: str, codec: str,
                   prores_profile: str, prores_qscale: str,
                   splash: Path = None, endboard: Path = None,
                   transition: str = TRANSITION_NONE, transition_duration: float = 1.0) -> list:
    """
    Builds an ffmpeg command that concatenates, in order:
        [splash (optional)] -> source (+ optional transition on its tail) -> [endboard (optional)]
    Every clip is normalized to the SOURCE video's resolution/fps/SAR.
    Audio is normalized across all clips; silence is generated for any clip
    that lacks an audio track.
    """
    src_info = probe(source)
    width, height, fps = src_info["width"], src_info["height"], src_info["fps"]

    clip_paths = []
    if splash is not None:
        clip_paths.append(splash)
    source_index_in_list = len(clip_paths)  # position of the source clip in clip_paths
    clip_paths.append(source)
    if endboard is not None:
        clip_paths.append(endboard)

    clip_infos = [probe(p) if p is not source else src_info for p in clip_paths]

    inputs = []
    for p in clip_paths:
        inputs += ["-i", str(p)]

    extra_silent_inputs = 0

    def add_silent_input(duration: float) -> int:
        nonlocal extra_silent_inputs
        inputs.extend(["-f", "lavfi", "-i",
                       f"anullsrc=channel_layout=stereo:sample_rate=48000:duration={duration:.3f}"])
        idx = len(clip_paths) + extra_silent_inputs
        extra_silent_inputs += 1
        return idx

    audio_sample_fmt = "s16" if codec == "prores" else "fltp"

    video_labels = []
    audio_labels = []
    filters = []

    for i, info in enumerate(clip_infos):
        transition_frag = ""
        if i == source_index_in_list:
            transition_frag = build_transition_fragment(info["duration"] or 0.0, transition, transition_duration)

        filters.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}{transition_frag}[v{i}]"
        )
        video_labels.append(f"[v{i}]")

        if info["has_audio"]:
            filters.append(
                f"[{i}:a]aformat=sample_fmts={audio_sample_fmt}:sample_rates=48000:"
                f"channel_layouts=stereo[a{i}]"
            )
        else:
            idx = add_silent_input(info["duration"] or 1.0)
            filters.append(f"[{idx}:a]anull[a{i}]")
        audio_labels.append(f"[a{i}]")

    n = len(clip_infos)
    concat_inputs = "".join(v + a for v, a in zip(video_labels, audio_labels))
    filter_complex = ";".join(filters)
    filter_complex += f";{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]"

    cmd = [resolve_binary("ffmpeg"), "-y"] + inputs + ["-filter_complex", filter_complex, "-map", "[outv]", "-map", "[outa]"]

    if codec == "prores":
        profile_num = PRORES_PROFILES.get(prores_profile, "2")
        pix_fmt = "yuv444p10le" if prores_profile == "4444" else "yuv422p10le"
        cmd += [
            "-c:v", "prores_ks", "-profile:v", profile_num, "-pix_fmt", pix_fmt,
            "-vendor", "apl0", "-qscale:v", prores_qscale,
            "-c:a", "pcm_s16le",
        ]
    else:
        cmd += [
            "-c:v", "libx264", "-crf", crf, "-preset", preset,
            "-c:a", "aac", "-b:a", "192k",
        ]

    cmd.append(str(output))
    return cmd
