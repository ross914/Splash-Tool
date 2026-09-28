"""
endboard_gui.py

A desktop GUI (Tkinter, built into Python - no extra install needed) for
applying a titlecard/splash to the start and/or an endboard to the end of
one or more videos, with an optional transition (crossfade to white, or
fade to black then white) applied to the source clip just before the
endboard cut.

Run directly with:
    python endboard_gui.py

To package as a standalone Windows .exe (so it can run without Python
installed), see the PACKAGING INSTRUCTIONS at the bottom of this file.
"""

import queue
import threading
import traceback
from pathlib import Path
from tkinter import (
    Tk, StringVar, DoubleVar, BooleanVar, filedialog, messagebox,
    N, S, E, W, END, DISABLED, NORMAL
)
from tkinter import ttk

import core_processing as core

VIDEO_EXTENSIONS = (".mov", ".mp4", ".mxf", ".avi", ".m4v")


def list_video_files(folder: Path):
    if not folder or not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_EXTENSIONS)


class EndboardApp:
    def __init__(self, root: Tk):
        self.root = root
        root.title("Splash & Endboard Batch Tool")
        root.geometry("760x680")
        root.minsize(700, 620)

        self.log_queue = queue.Queue()
        self.worker_thread = None
        self.cancel_requested = False

        # ---- state ----
        self.input_mode = StringVar(value="folder")          # "folder" or "files"
        self.input_path = StringVar()
        self.selected_files = []                               # used when input_mode == "files"

        self.titlecard_library = StringVar()
        self.titlecard_choice = StringVar(value="(None)")
        self.titlecard_custom_path = StringVar()

        self.endcard_library = StringVar()
        self.endcard_choice = StringVar(value="(None)")
        self.endcard_custom_path = StringVar()

        self.transition_choice = StringVar(value=core.TRANSITION_NONE)
        self.transition_duration = DoubleVar(value=1.0)

        self.output_path = StringVar()
        self.file_ext = StringVar(value="mov")

        self.codec_choice = StringVar(value="prores")
        self.prores_profile = StringVar(value="standard")
        self.prores_qscale = StringVar(value="4")
        self.h264_crf = StringVar(value="18")
        self.h264_preset = StringVar(value="medium")

        self.progress_value = DoubleVar(value=0)
        self.status_text = StringVar(value="Idle")

        self._build_ui()
        self.root.after(150, self._poll_log_queue)

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}
        nb = ttk.Notebook(self.root)
        nb.grid(row=0, column=0, sticky=(N, S, E, W))
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main_tab = ttk.Frame(nb)
        settings_tab = ttk.Frame(nb)
        nb.add(main_tab, text="Process Videos")
        nb.add(settings_tab, text="Output Settings")

        main_tab.columnconfigure(1, weight=1)

        # --- Input section ---
        row = 0
        ttk.Label(main_tab, text="Source", font=("", 10, "bold")).grid(row=row, column=0, sticky=W, **pad)
        row += 1

        mode_frame = ttk.Frame(main_tab)
        mode_frame.grid(row=row, column=0, columnspan=3, sticky=W, **pad)
        ttk.Radiobutton(mode_frame, text="Folder of videos (batch)", variable=self.input_mode,
                         value="folder", command=self._refresh_input_widgets).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(mode_frame, text="Individual file(s)", variable=self.input_mode,
                         value="files", command=self._refresh_input_widgets).pack(side="left")
        row += 1

        self.input_entry = ttk.Entry(main_tab, textvariable=self.input_path)
        self.input_entry.grid(row=row, column=0, columnspan=2, sticky=(E, W), **pad)
        self.input_browse_btn = ttk.Button(main_tab, text="Browse...", command=self._browse_input)
        self.input_browse_btn.grid(row=row, column=2, sticky=W, **pad)
        row += 1

        ttk.Label(main_tab, text="Extension filter (folder mode only):").grid(row=row, column=0, sticky=W, **pad)
        ttk.Entry(main_tab, textvariable=self.file_ext, width=8).grid(row=row, column=1, sticky=W, **pad)
        row += 1

        ttk.Separator(main_tab).grid(row=row, column=0, columnspan=3, sticky=(E, W), pady=8)
        row += 1

        # --- Titlecard section ---
        ttk.Label(main_tab, text="Titlecard (start)", font=("", 10, "bold")).grid(row=row, column=0, sticky=W, **pad)
        row += 1
        ttk.Label(main_tab, text="Library folder:").grid(row=row, column=0, sticky=W, **pad)
        ttk.Entry(main_tab, textvariable=self.titlecard_library).grid(row=row, column=1, sticky=(E, W), **pad)
        ttk.Button(main_tab, text="Browse...",
                   command=lambda: self._browse_library(self.titlecard_library, self.title_combo)).grid(
            row=row, column=2, sticky=W, **pad)
        row += 1
        ttk.Label(main_tab, text="Choose titlecard:").grid(row=row, column=0, sticky=W, **pad)
        self.title_combo = ttk.Combobox(main_tab, textvariable=self.titlecard_choice,
                                         values=["(None)"], state="readonly")
        self.title_combo.grid(row=row, column=1, sticky=(E, W), **pad)
        ttk.Button(main_tab, text="Custom file...",
                   command=lambda: self._browse_custom_asset(self.titlecard_custom_path, self.titlecard_choice)).grid(
            row=row, column=2, sticky=W, **pad)
        row += 1

        ttk.Separator(main_tab).grid(row=row, column=0, columnspan=3, sticky=(E, W), pady=8)
        row += 1

        # --- Endcard section ---
        ttk.Label(main_tab, text="Endboard (end)", font=("", 10, "bold")).grid(row=row, column=0, sticky=W, **pad)
        row += 1
        ttk.Label(main_tab, text="Library folder:").grid(row=row, column=0, sticky=W, **pad)
        ttk.Entry(main_tab, textvariable=self.endcard_library).grid(row=row, column=1, sticky=(E, W), **pad)
        ttk.Button(main_tab, text="Browse...",
                   command=lambda: self._browse_library(self.endcard_library, self.end_combo)).grid(
            row=row, column=2, sticky=W, **pad)
        row += 1
        ttk.Label(main_tab, text="Choose endboard:").grid(row=row, column=0, sticky=W, **pad)
        self.end_combo = ttk.Combobox(main_tab, textvariable=self.endcard_choice,
                                       values=["(None)"], state="readonly")
        self.end_combo.grid(row=row, column=1, sticky=(E, W), **pad)
        ttk.Button(main_tab, text="Custom file...",
                   command=lambda: self._browse_custom_asset(self.endcard_custom_path, self.endcard_choice)).grid(
            row=row, column=2, sticky=W, **pad)
        row += 1

        # --- Transition section ---
        ttk.Label(main_tab, text="Transition before endboard:").grid(row=row, column=0, sticky=W, **pad)
        trans_frame = ttk.Frame(main_tab)
        trans_frame.grid(row=row, column=1, columnspan=2, sticky=W, **pad)
        ttk.Radiobutton(trans_frame, text="None", variable=self.transition_choice,
                         value=core.TRANSITION_NONE).pack(anchor=W)
        ttk.Radiobutton(trans_frame, text="Crossfade to white", variable=self.transition_choice,
                         value=core.TRANSITION_CROSSFADE_WHITE).pack(anchor=W)
        ttk.Radiobutton(trans_frame, text="Fade to black, then white", variable=self.transition_choice,
                         value=core.TRANSITION_FADE_BLACK_WHITE).pack(anchor=W)
        row += 1

        ttk.Label(main_tab, text="Transition duration (seconds):").grid(row=row, column=0, sticky=W, **pad)
        ttk.Spinbox(main_tab, from_=0.2, to=10.0, increment=0.1, textvariable=self.transition_duration,
                    width=8).grid(row=row, column=1, sticky=W, **pad)
        row += 1

        ttk.Separator(main_tab).grid(row=row, column=0, columnspan=3, sticky=(E, W), pady=8)
        row += 1

        # --- Output section ---
        ttk.Label(main_tab, text="Output folder:").grid(row=row, column=0, sticky=W, **pad)
        ttk.Entry(main_tab, textvariable=self.output_path).grid(row=row, column=1, sticky=(E, W), **pad)
        ttk.Button(main_tab, text="Browse...", command=self._browse_output).grid(row=row, column=2, sticky=W, **pad)
        row += 1

        # --- Run controls ---
        run_frame = ttk.Frame(main_tab)
        run_frame.grid(row=row, column=0, columnspan=3, sticky=(E, W), **pad)
        run_frame.columnconfigure(0, weight=1)
        self.run_btn = ttk.Button(run_frame, text="Run", command=self._start_processing)
        self.run_btn.grid(row=0, column=0, sticky=W)
        self.cancel_btn = ttk.Button(run_frame, text="Cancel", command=self._cancel_processing, state=DISABLED)
        self.cancel_btn.grid(row=0, column=1, sticky=W, padx=(8, 0))
        row += 1

        self.progress_bar = ttk.Progressbar(main_tab, variable=self.progress_value, maximum=100)
        self.progress_bar.grid(row=row, column=0, columnspan=3, sticky=(E, W), **pad)
        row += 1

        ttk.Label(main_tab, textvariable=self.status_text).grid(row=row, column=0, columnspan=3, sticky=W, **pad)
        row += 1

        import tkinter as tk
        self.log_box = tk.Text(main_tab, height=10, state=DISABLED, wrap="word")
        self.log_box.grid(row=row, column=0, columnspan=3, sticky=(N, S, E, W), **pad)
        main_tab.rowconfigure(row, weight=1)

        # --- Settings tab ---
        srow = 0
        ttk.Label(settings_tab, text="Output codec:", font=("", 10, "bold")).grid(row=srow, column=0, sticky=W, **pad)
        codec_frame = ttk.Frame(settings_tab)
        codec_frame.grid(row=srow, column=1, sticky=W, **pad)
        ttk.Radiobutton(codec_frame, text="ProRes", variable=self.codec_choice, value="prores",
                         command=self._refresh_codec_widgets).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(codec_frame, text="H.264", variable=self.codec_choice, value="h264",
                         command=self._refresh_codec_widgets).pack(side="left")
        srow += 1

        self.prores_frame = ttk.LabelFrame(settings_tab, text="ProRes settings")
        self.prores_frame.grid(row=srow, column=0, columnspan=2, sticky=(E, W), **pad)
        ttk.Label(self.prores_frame, text="Profile:").grid(row=0, column=0, sticky=W, **pad)
        ttk.Combobox(self.prores_frame, textvariable=self.prores_profile,
                     values=["proxy", "lt", "standard", "hq", "4444"], state="readonly", width=12).grid(
            row=0, column=1, sticky=W, **pad)
        ttk.Label(self.prores_frame,
                  text="Quality/bitrate (qscale). Lower = higher bitrate:").grid(row=1, column=0, sticky=W, **pad)
        ttk.Spinbox(self.prores_frame, from_=1, to=31, textvariable=self.prores_qscale, width=6).grid(
            row=1, column=1, sticky=W, **pad)
        srow += 1

        self.h264_frame = ttk.LabelFrame(settings_tab, text="H.264 settings")
        self.h264_frame.grid(row=srow, column=0, columnspan=2, sticky=(E, W), **pad)
        ttk.Label(self.h264_frame, text="CRF (lower = higher quality):").grid(row=0, column=0, sticky=W, **pad)
        ttk.Spinbox(self.h264_frame, from_=0, to=51, textvariable=self.h264_crf, width=6).grid(
            row=0, column=1, sticky=W, **pad)
        ttk.Label(self.h264_frame, text="Preset:").grid(row=1, column=0, sticky=W, **pad)
        ttk.Combobox(self.h264_frame, textvariable=self.h264_preset,
                     values=["ultrafast", "fast", "medium", "slow", "veryslow"],
                     state="readonly", width=12).grid(row=1, column=1, sticky=W, **pad)
        srow += 1

        self._refresh_codec_widgets()
        self._refresh_input_widgets()

    # ------------------------------------------------------------ helpers

    def _refresh_codec_widgets(self):
        if self.codec_choice.get() == "prores":
            self.prores_frame.grid()
            self.h264_frame.grid_remove()
        else:
            self.h264_frame.grid()
            self.prores_frame.grid_remove()

    def _refresh_input_widgets(self):
        # entry stays usable either way; label context switches via placeholder text is skipped for simplicity
        pass

    def _browse_input(self):
        if self.input_mode.get() == "folder":
            path = filedialog.askdirectory(title="Select folder of source videos")
            if path:
                self.input_path.set(path)
        else:
            paths = filedialog.askopenfilenames(title="Select one or more source videos")
            if paths:
                self.selected_files = list(paths)
                self.input_path.set("; ".join(Path(p).name for p in paths))

    def _browse_library(self, library_var: StringVar, combo: ttk.Combobox):
        path = filedialog.askdirectory(title="Select folder containing titlecard/endboard options")
        if not path:
            return
        library_var.set(path)
        files = list_video_files(Path(path))
        values = ["(None)"] + [f.name for f in files]
        combo["values"] = values
        if combo.get() not in values:
            combo.set("(None)")

    def _browse_custom_asset(self, custom_var: StringVar, choice_var: StringVar):
        path = filedialog.askopenfilename(title="Select a video file")
        if path:
            custom_var.set(path)
            choice_var.set(f"[custom] {Path(path).name}")

    def _browse_output(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_path.set(path)

    def _resolve_asset(self, library_var: StringVar, choice_var: StringVar, custom_var: StringVar):
        """Returns a Path or None for the currently selected titlecard/endcard."""
        choice = choice_var.get()
        if choice == "(None)" or not choice:
            return None
        if choice.startswith("[custom] "):
            custom = custom_var.get()
            return Path(custom) if custom else None
        library = library_var.get()
        if not library:
            return None
        return Path(library) / choice

    # ------------------------------------------------------------ run logic

    def _gather_jobs(self):
        if self.input_mode.get() == "folder":
            folder = Path(self.input_path.get())
            if not folder.is_dir():
                raise ValueError("Please choose a valid input folder.")
            ext = self.file_ext.get().lstrip(".") or "mov"
            files = sorted(folder.glob(f"*.{ext}"))
            if not files:
                raise ValueError(f"No .{ext} files found in {folder}")
            return files
        else:
            if not self.selected_files:
                raise ValueError("Please choose one or more source video files.")
            return [Path(p) for p in self.selected_files]

    def _start_processing(self):
        try:
            jobs = self._gather_jobs()
            output_dir = Path(self.output_path.get())
            if not self.output_path.get():
                raise ValueError("Please choose an output folder.")
            output_dir.mkdir(parents=True, exist_ok=True)

            splash = self._resolve_asset(self.titlecard_library, self.titlecard_choice, self.titlecard_custom_path)
            endboard = self._resolve_asset(self.endcard_library, self.endcard_choice, self.endcard_custom_path)

            if splash is not None and not splash.exists():
                raise ValueError(f"Titlecard file not found: {splash}")
            if endboard is not None and not endboard.exists():
                raise ValueError(f"Endboard file not found: {endboard}")
            if splash is None and endboard is None:
                raise ValueError("Choose at least a titlecard or an endboard (or both).")

        except ValueError as e:
            messagebox.showerror("Cannot start", str(e))
            return

        params = dict(
            jobs=jobs,
            output_dir=output_dir,
            splash=splash,
            endboard=endboard,
            transition=self.transition_choice.get(),
            transition_duration=self.transition_duration.get(),
            codec=self.codec_choice.get(),
            prores_profile=self.prores_profile.get(),
            prores_qscale=self.prores_qscale.get(),
            crf=self.h264_crf.get(),
            preset=self.h264_preset.get(),
        )

        self.run_btn.config(state=DISABLED)
        self.cancel_btn.config(state=NORMAL)
        self.cancel_requested = False
        self.progress_value.set(0)
        self._clear_log()

        self.worker_thread = threading.Thread(target=self._worker, kwargs=params, daemon=True)
        self.worker_thread.start()

    def _cancel_processing(self):
        self.cancel_requested = True
        self._log("Cancel requested - will stop after the current file finishes...")

    def _worker(self, jobs, output_dir, splash, endboard, transition, transition_duration,
                codec, prores_profile, prores_qscale, crf, preset):
        total = len(jobs)
        succeeded = 0
        failures = []

        for i, source in enumerate(jobs, 1):
            if self.cancel_requested:
                self._log(f"Cancelled after {i - 1}/{total} files.")
                break

            self._log(f"[{i}/{total}] {source.name}")
            output_path = output_dir / source.name
            try:
                cmd = core.build_command(
                    source, output_path, crf, preset, codec, prores_profile, prores_qscale,
                    splash=splash, endboard=endboard,
                    transition=transition, transition_duration=transition_duration,
                )
                import subprocess
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    err = result.stderr.strip().splitlines()[-1] if result.stderr else "unknown error"
                    self._log(f"    FAILED: {err}")
                    failures.append((source.name, err))
                else:
                    self._log(f"    Done -> {output_path}")
                    succeeded += 1
            except Exception as e:
                self._log(f"    ERROR: {e}")
                self._log(traceback.format_exc())
                failures.append((source.name, str(e)))

            self.progress_value.set(int(i / total * 100))
            self.status_text.set(f"{i}/{total} processed")

        self._log(f"\nCompleted: {succeeded}/{total} succeeded.")
        if failures:
            self._log("Failures:")
            for name, err in failures:
                self._log(f"  - {name}: {err}")

        self.status_text.set("Done" if not self.cancel_requested else "Cancelled")
        self.run_btn.config(state=NORMAL)
        self.cancel_btn.config(state=DISABLED)

    # ------------------------------------------------------------ log/UI thread-safety

    def _log(self, message: str):
        self.log_queue.put(message)

    def _clear_log(self):
        self.log_box.config(state=NORMAL)
        self.log_box.delete("1.0", END)
        self.log_box.config(state=DISABLED)

    def _poll_log_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_box.config(state=NORMAL)
                self.log_box.insert(END, message + "\n")
                self.log_box.see(END)
                self.log_box.config(state=DISABLED)
        except queue.Empty:
            pass
        self.root.after(150, self._poll_log_queue)


def main():
    root = Tk()
    app = EndboardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()


# ======================================================================
# PACKAGING INSTRUCTIONS - turning this into a standalone Windows .exe
# ======================================================================
#
# This has to be done ON A WINDOWS MACHINE (PyInstaller builds an exe for
# whatever OS you run it on - it can't cross-compile a Windows .exe from
# macOS or Linux). Steps:
#
# 1. Install Python on the Windows machine if not already there (python.org,
#    tick "Add to PATH" during install).
#
# 2. Install ffmpeg on that Windows machine too (the exe still needs ffmpeg/
#    ffprobe available - either on PATH, or placed in the same folder as the
#    exe; ffmpeg.org has Windows builds).
#
# 3. Open PowerShell in the folder containing endboard_gui.py and
#    core_processing.py, then run:
#
#        pip install pyinstaller
#        pyinstaller --onefile --windowed --name "SplashEndboardTool" endboard_gui.py
#
# 4. The finished .exe will be in the newly created "dist" folder:
#        dist\SplashEndboardTool.exe
#
#    That single file can be copied anywhere and double-clicked to run -
#    no need to keep the .py files around once it's built, though ffmpeg/
#    ffprobe still need to be reachable (on PATH, or sitting next to the
#    exe) since the exe calls out to them rather than bundling them.
#
# 5. If Windows Defender/SmartScreen flags the exe as unrecognized (common
#    for freshly-built, unsigned executables), that's expected the first
#    time - "More info" -> "Run anyway" to bypass it, or get it code-signed
#    if you're planning to distribute it more widely across the team.
