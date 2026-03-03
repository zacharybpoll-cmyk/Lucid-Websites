# Lucid — Voice Wellness Monitor

## What
macOS menubar app. Passive voice analysis (Kintsugi DAM model). Detects stress, mood, energy, depression risk. All local/private — no cloud processing.

## Tech Stack
FastAPI + pywebview + pystray + Silero VAD + Kintsugi DAM + SQLite

## Source & Deploy Locations
- **Source**: `/Users/zacharypoll/Desktop/Documents/Claude Code/Lucid/`
- **App**: `~/Desktop/Lucid.app` (bundle ID: `com.electron.lucid`)

## App Isolation

Lucid is fully independent from other app variants:

| App | Bundle ID | Package Name | userData Dir | Source |
|-----|-----------|-------------|--------------|--------|
| Lucid | `com.electron.lucid` | `lucid` | `~/Library/Application Support/lucid/` | Lucid |

**CRITICAL**: Never change `"name"` in `package.json` without updating build commands. The name determines the userData directory.

## Deploy Procedures

### Fast-Deploy (1-3 file changes)
```bash
# 1. Copy changed files into app bundle
cp <changed-files> ~/Desktop/"Lucid.app"/Contents/Resources/python/

# 2. Clear Electron HTTP cache (MANDATORY — Chromium serves stale JS without this)
rm -rf ~/Library/Application\ Support/lucid/Cache ~/Library/Application\ Support/lucid/Code\ Cache

# 3. Kill and relaunch
pkill -f "Lucid" 2>/dev/null || true; lsof -ti TCP:8767 | xargs kill -9 2>/dev/null || true; sleep 1 && open ~/Desktop/"Lucid.app"

# 4. ALWAYS screenshot after relaunch to confirm changes are live
```

### Full Rebuild (many files or structural changes)
```bash
cd "/Users/zacharypoll/Desktop/Documents/Claude Code/Lucid" && \
pkill -f "Lucid" 2>/dev/null || true; lsof -ti TCP:8767 | xargs kill -9 2>/dev/null || true; sleep 2 && \
npx electron-packager . "Lucid" --platform=darwin --arch=arm64 \
  --icon=assets/icon.icns --app-bundle-id=com.electron.lucid \
  --app-version=1.0.0 \
  --ignore='^/.*-darwin-arm64$' --ignore='^/\.git' --ignore='^/python' \
  --ignore='^\/(Business|claude-dashboard|lucid-website|scripts|build)' \
  --ignore='\.(docx|pdf|zip|png|pptx)$' \
  --overwrite && \
cp -R python "./Lucid-darwin-arm64/Lucid.app/Contents/Resources/" && \
rm -rf ~/Desktop/"Lucid.app" && \
mv "./Lucid-darwin-arm64/Lucid.app" ~/Desktop/"Lucid.app" && \
codesign --sign - --force --deep ~/Desktop/"Lucid.app"

# Clear cache after rebuild
rm -rf ~/Library/Application\ Support/lucid/Cache ~/Library/Application\ Support/lucid/Code\ Cache
```

## Test Command
No automated test suite yet. Manual verification:
```bash
# 1. Start the app
open ~/Desktop/"Lucid.app"

# 2. Verify backend health
curl -s http://localhost:8767/api/health | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('ready')==True, f'Not ready: {d}'; print('PASS: Backend ready')"

# 3. Verify key endpoints return valid JSON
curl -s http://localhost:8767/api/dashboard | python3 -c "import sys,json; json.load(sys.stdin); print('PASS: Dashboard endpoint OK')"
```

## Current Version
v1.0.0

## Shared Lessons
All app variants share one lessons file: `/Users/zacharypoll/Desktop/Documents/Claude Code/shared/lucid-lessons.md`

## Known Hardcoded Values
- `app.js`: Speaker Gate debug threshold display reads `adaptive_threshold` from gate stats dynamically
- Momentum still hardcoded as `0.24`

## Error Monitoring & Crash Reporting

Log locations under `~/Library/Application Support/lucid/`:
- `crash_log.txt` — Electron + Python uncaught exceptions (sanitized)
- `lucid.log` — Python rotating log (5MB, 3 backups)

## Performance Benchmarks

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Startup → splash | <2s | Time from `open` to splash |
| Splash → ready | <15s | Until `/api/health` returns `ready: true` |
| Memory (idle) | <500MB | `ps aux \| grep lucid` |
| Memory (active) | <1.5GB | Same during analysis |

## Code Signing & Notarization

Substitute `com.electron.lucid` for bundle ID and `"Lucid"` for app name in the standard code signing workflow.

## Dependency Audit
```bash
cd "/Users/zacharypoll/Desktop/Documents/Claude Code/Lucid"
npm audit
cd python && ./venv/bin/pip audit 2>/dev/null || echo "pip-audit not installed"
```

## API Reference
Same 61 endpoints on port 8767. Full docs: `/Users/zacharypoll/Desktop/Documents/Claude Code/shared/lucid-api-reference.md`
