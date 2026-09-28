# Splash & Endboard Tool — Building Windows + Mac Apps

This folder is a ready-to-go project. Once it's in a GitHub repository,
GitHub will automatically build a **native Windows .exe** and a **native
Mac app** for you — each with ffmpeg bundled inside, so nobody on the team
needs Python or ffmpeg installed separately to use the finished app.

## Why this is necessary

Packaging tools like PyInstaller can only build for the operating system
they're actually running on — there's no way to produce a Mac app from
Windows/Linux, or a Windows .exe from a Mac, on a single machine. GitHub
Actions solves this by running the build on real Windows and Mac machines
in the cloud, automatically, every time you push a change.

## One-time setup

1. **Create a free GitHub account** at github.com if you don't already have one.
2. **Create a new repository** (the "+" icon top-right → "New repository").
   Doesn't matter if it's public or private — private is fine and free for
   this.
3. **Upload this whole folder** into that repository. Easiest way if you're
   not familiar with git: on the repo's GitHub page, use "Add file" →
   "Upload files", then drag in:
   - `core_processing.py`
   - `endboard_gui.py`
   - the `.github` folder (make sure the `.github/workflows/build.yml` path
     is preserved — GitHub's drag-and-drop upload keeps folder structure, so
     dragging the whole project folder in one go works)
4. Commit the upload (the green "Commit changes" button).

That's it — pushing the files triggers the build automatically.

## Getting your apps

1. Go to the **Actions** tab in your repository.
2. You'll see a running (or completed) workflow called "Build Splash &
   Endboard Tool" — click it.
3. Wait for both jobs (windows-latest, macos-latest) to show a green
   checkmark — usually a few minutes.
4. Scroll down to **Artifacts** and download:
   - `SplashEndboardTool-windows` → unzip it, run `SplashEndboardTool.exe`
   - `SplashEndboardTool-mac` → unzip it, run `SplashEndboardTool`
     (macOS will likely show an "unidentified developer" warning the first
     time — right-click the app → Open, then confirm, to bypass it once)

Each of these is fully standalone — ffmpeg is bundled inside, so they'll
run on any teammate's machine without installing anything else first.

## Making changes later

Any time you want to update the tool (new feature, bug fix), just upload
the changed `.py` file(s) back into the same repo the same way — GitHub
will automatically rebuild both apps within a few minutes, and new
artifacts will appear in the Actions tab.

## A note on ffmpeg licensing

The bundled Windows ffmpeg build uses the "gpl" variant (needed for full
feature support). If this stays an internal Makematic tool, that's not an
issue. If you ever plan to distribute it outside the company, it's worth
being aware that GPL-licensed components carry source-availability
obligations — worth a quick check with whoever handles that at Makematic
before wider distribution.

## Prefer not to use GitHub?

You can still build each app manually, it just takes doing it once on each
actual machine:

**On a Windows machine:**
```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --name "SplashEndboardTool" endboard_gui.py
```

**On a Mac:**
```bash
pip3 install pyinstaller
pyinstaller --onefile --windowed --name "SplashEndboardTool" endboard_gui.py
```

The difference: this way, ffmpeg needs to be separately installed on
whichever machine runs the resulting app (since it isn't bundled in), and
you'd need to repeat the build step on each OS yourself every time you
change the code. The GitHub Actions route above avoids both of those.
