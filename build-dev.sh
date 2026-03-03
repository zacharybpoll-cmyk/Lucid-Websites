#!/usr/bin/env bash
# ============================================================
# Lucid — Dev Build Script
# Builds the dev variant without touching production files.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="Lucid Dev"
BUILD_DIR="${APP_NAME}-darwin-arm64"
BUNDLE_ID="com.electron.lucid-dev"
VERSION="1.0.0-dev"

echo "=== Lucid Dev — Build ==="
echo "Source: $SCRIPT_DIR"
echo "Output: $SCRIPT_DIR/$BUILD_DIR/$APP_NAME.app"
echo ""

# 1. Kill any running dev instance
echo "[1/5] Stopping existing dev instance..."
pkill -f "Lucid Dev" 2>/dev/null || true
sleep 1

# 2. Swap package.json for dev variant
echo "[2/5] Swapping package.json -> package-dev.json..."
cp package.json package.json.bak
cp package-dev.json package.json

# 3. Build with electron-packager
echo "[3/5] Running electron-packager..."
npx electron-packager . "$APP_NAME" \
  --platform=darwin \
  --arch=arm64 \
  --icon=assets/icon.icns \
  --app-bundle-id="$BUNDLE_ID" \
  --app-version="$VERSION" \
  --extra-resource=python \
  --ignore="^/${BUILD_DIR//\//\\/}$" \
  --ignore="^/Lucid-darwin-arm64$" \
  --ignore='^\/(\.git|\.github|node_modules\/\.cache)' \
  --overwrite

# 4. Restore original package.json
echo "[4/5] Restoring original package.json..."
mv package.json.bak package.json

# 5. Clear dev app cache
echo "[5/5] Clearing dev app cache..."
rm -rf ~/Library/Application\ Support/lucid-dev/Cache \
       ~/Library/Application\ Support/lucid-dev/Code\ Cache \
       2>/dev/null || true

echo ""
echo "=== Build complete ==="
echo "App: $SCRIPT_DIR/$BUILD_DIR/$APP_NAME.app"
echo ""
echo "To launch:"
echo "  open \"$SCRIPT_DIR/$BUILD_DIR/$APP_NAME.app\""
