============================================================
  Attune Health v1.0.0 — Installation Guide
============================================================

Attune Health is a voice wellness monitor that runs entirely
on your Mac. It analyzes your voice to track stress, mood,
energy, and emotional wellbeing throughout the day.

ALL processing happens locally — no data ever leaves your Mac.

------------------------------------------------------------
  SYSTEM REQUIREMENTS
------------------------------------------------------------

- Apple Silicon Mac (M1, M2, M3, M4, or Pro/Max/Ultra)
- macOS 13 (Ventura) or later
- ~3 GB free disk space
- Built-in or external microphone

Intel Macs are NOT supported.

------------------------------------------------------------
  INSTALLATION
------------------------------------------------------------

1. Unzip "Attune-Health-v1.0.0-arm64.zip"
   (double-click or: unzip Attune-Health-v1.0.0-arm64.zip)

2. Drag "Attune Health.app" to your Applications folder
   (or leave it wherever you prefer)

3. Double-click to launch

------------------------------------------------------------
  GATEKEEPER / SECURITY WARNING
------------------------------------------------------------

Because this app is not distributed through the Mac App Store,
macOS will block it on first launch. To bypass this:

  macOS Sequoia (15) and later:
  1. Double-click the app — you'll see "cannot be opened"
  2. Open System Settings > Privacy & Security
  3. Scroll down — you'll see a message about "Attune Health"
  4. Click "Open Anyway"
  5. Enter your password when prompted
  6. The app will now launch normally every time

  Alternative (Terminal):
  xattr -cr "/Applications/Attune Health.app"

------------------------------------------------------------
  FIRST LAUNCH
------------------------------------------------------------

- The app will ask for microphone permission — click Allow
- A brief onboarding will walk you through setup
- First analysis takes ~10-15 seconds to load ML models
- After that, analyses are near-instant

------------------------------------------------------------
  PRIVACY
------------------------------------------------------------

- All voice analysis runs locally on your Mac
- No audio is sent to any server
- No internet connection required for core features
- Your wellness data is stored only in:
  ~/Library/Application Support/attune/attune-data/

------------------------------------------------------------
  TROUBLESHOOTING
------------------------------------------------------------

App won't open:
  See "Gatekeeper" section above

No microphone access:
  System Settings > Privacy & Security > Microphone
  Make sure "Attune Health" is toggled ON

App crashes on launch:
  1. Delete ~/Library/Application Support/Attune Health/
  2. Try launching again

Need help:
  Reach out to Zach directly

============================================================
