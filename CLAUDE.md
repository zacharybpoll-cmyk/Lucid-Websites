# Attune Steel — Voice Wellness Monitor (Steel Edition)

## What
macOS menubar app. Passive voice analysis (Kintsugi DAM model). Detects stress, mood, energy, depression risk. All local/private — no cloud processing.

## Tech Stack
FastAPI + pywebview + pystray + Silero VAD + Kintsugi DAM + SQLite

## Source & Deploy Locations
- **Source**: `/Users/zacharypoll/Desktop/Documents/Claude Code/Attune-Steel/`
- **App**: `~/Desktop/Attune Steel.app` (bundle ID: `com.electron.attune-steel`)

## App Isolation

Attune Steel is fully independent from Attune (Dev) and Attune Health:

| App | Bundle ID | Package Name | userData Dir | Source |
|-----|-----------|-------------|--------------|--------|
| Attune Steel | `com.electron.attune-steel` | `attune-steel` | `~/Library/Application Support/attune-steel/` | Attune-Steel |
| Attune (Dev) | `com.electron.attune-dev` | `attune-dev` | `~/Library/Application Support/attune-dev/` | Attune |
| Attune Health | `com.electron.attune-health` | `attune-health` | `~/Library/Application Support/attune-health/` | Attune-Health |

**CRITICAL**: Never change `"name"` in `package.json` without updating build commands. The name determines the userData directory.

## Deploy Procedures

### Fast-Deploy (1-3 file changes)
```bash
# 1. Copy changed files into app bundle
cp <changed-files> ~/Desktop/"Attune Steel.app"/Contents/Resources/python/

# 2. Clear Electron HTTP cache (MANDATORY — Chromium serves stale JS without this)
rm -rf ~/Library/Application\ Support/attune-steel/Cache ~/Library/Application\ Support/attune-steel/Code\ Cache

# 3. Kill and relaunch
pkill -f "Attune Steel" || true && sleep 1 && open ~/Desktop/"Attune Steel.app"

# 4. ALWAYS screenshot after relaunch to confirm changes are live
```

### Full Rebuild (many files or structural changes)
```bash
cd "/Users/zacharypoll/Desktop/Documents/Claude Code/Attune-Steel" && \
pkill -f "Attune Steel" || true && \
npx electron-packager . "Attune Steel" --platform=darwin --arch=arm64 \
  --icon=assets/icon.icns --app-bundle-id=com.electron.attune-steel \
  --app-version=1.0.0 --extra-resource=python \
  --ignore='^/.*-darwin-arm64$' --ignore='^/\.git' --ignore='^/python' --overwrite && \
rm -rf ~/Desktop/"Attune Steel.app" && \
mv "./Attune Steel-darwin-arm64/Attune Steel.app" ~/Desktop/"Attune Steel.app" && \
codesign --sign - --force --deep ~/Desktop/"Attune Steel.app"

# Clear cache after rebuild
rm -rf ~/Library/Application\ Support/attune-steel/Cache ~/Library/Application\ Support/attune-steel/Code\ Cache
```

## Test Command
No automated test suite yet. Manual verification:
```bash
# 1. Start the app
open ~/Desktop/"Attune Steel.app"

# 2. Verify backend health
curl -s http://localhost:8767/api/health | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('ready')==True, f'Not ready: {d}'; print('PASS: Backend ready')"

# 3. Verify key endpoints return valid JSON
curl -s http://localhost:8767/api/dashboard | python3 -c "import sys,json; json.load(sys.stdin); print('PASS: Dashboard endpoint OK')"
```

## Current Version
v1.0.0

## Shared Lessons
All Attune variants share one lessons file: `/Users/zacharypoll/Desktop/Documents/Claude Code/shared/attune-lessons.md`

## Known Hardcoded Values
- `app.js`: Speaker Gate debug threshold display reads `adaptive_threshold` from gate stats dynamically
- Momentum still hardcoded as `0.24`

## Error Monitoring & Crash Reporting

Same architecture as Attune Dev. Log locations under `~/Library/Application Support/attune-steel/`:
- `crash_log.txt` — Electron + Python uncaught exceptions (sanitized)
- `attune.log` — Python rotating log (5MB, 3 backups)

## Performance Benchmarks

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Startup → splash | <2s | Time from `open` to splash |
| Splash → ready | <15s | Until `/api/health` returns `ready: true` |
| Memory (idle) | <500MB | `ps aux \| grep attune-steel` |
| Memory (active) | <1.5GB | Same during analysis |

## Code Signing & Notarization

See Attune Dev CLAUDE.md for full workflow — substitute `com.electron.attune-steel` for bundle ID and `"Attune Steel"` for app name.

## Dependency Audit
```bash
cd "/Users/zacharypoll/Desktop/Documents/Claude Code/Attune-Steel"
npm audit
cd python && ./venv/bin/pip audit 2>/dev/null || echo "pip-audit not installed"
```

## API Reference
Same 61 endpoints as Attune Dev on port 8767. Full docs: `/Users/zacharypoll/Desktop/Documents/Claude Code/shared/attune-api-reference.md`
