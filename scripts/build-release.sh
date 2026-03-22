#!/usr/bin/env bash
# build-release.sh — Notarized release build for Lucid
# Creates a signed, notarized DMG + ZIP + update manifest for distribution.
#
# Prerequisites:
#   - Apple Developer ID Application certificate installed in Keychain
#   - Notarytool credentials stored: xcrun notarytool store-credentials "LucidNotary" ...
#   - create-dmg installed: brew install create-dmg
#
# Usage:
#   IDENTITY="Developer ID Application: Your Name (TEAMID)" ./scripts/build-release.sh
#   or:
#   ./scripts/build-release.sh --identity "Developer ID Application: ..." --notary-profile "LucidNotary"
#
# Dry run (skip signing/notarization, just build):
#   DRY_RUN=1 ./scripts/build-release.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# ============ Parse arguments ============
DRY_RUN="${DRY_RUN:-0}"
IDENTITY="${IDENTITY:-}"
NOTARY_PROFILE="${NOTARY_PROFILE:-LucidNotary}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --identity) IDENTITY="$2"; shift 2 ;;
    --notary-profile) NOTARY_PROFILE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# Read version from package.json
VERSION=$(node -p "require('./package.json').version")
ENTITLEMENTS="$ROOT/entitlements.plist"

echo "=== Lucid Release Build v${VERSION} ==="
echo "Root: $ROOT"
echo "Identity: ${IDENTITY:-<dry-run>}"
echo "Notary profile: $NOTARY_PROFILE"
echo "Dry run: $DRY_RUN"
echo ""

# Validate prerequisites
if [[ "$DRY_RUN" == "0" ]]; then
  if [[ -z "$IDENTITY" ]]; then
    echo "ERROR: IDENTITY is required for release builds."
    echo "  export IDENTITY=\"Developer ID Application: Your Name (TEAMID)\""
    echo "  or pass --dry-run to skip signing"
    exit 1
  fi
  if ! command -v create-dmg &>/dev/null; then
    echo "ERROR: create-dmg not found. Install with: brew install create-dmg"
    exit 1
  fi
fi

# ============ Step 1: Run base build ============
echo "--- Running base distribution build..."
bash "$ROOT/scripts/build-dist.sh"

# The base build puts the app at ~/Desktop/Lucid.app
# Move it to dist/ for release processing
mkdir -p "$ROOT/dist"
APP_PATH="$ROOT/dist/Lucid.app"
rm -rf "$APP_PATH"
mv ~/Desktop/"Lucid.app" "$APP_PATH"

RESOURCES="$APP_PATH/Contents/Resources"
FRAMEWORKS="$APP_PATH/Contents/Frameworks"

# ============ Step 2: Copy app-update.yml into bundle ============
if [[ -f "$ROOT/app-update.yml" ]]; then
  echo "--- Copying app-update.yml into bundle Resources..."
  cp "$ROOT/app-update.yml" "$RESOURCES/app-update.yml"
fi

# ============ Step 3: Code signing ============
if [[ "$DRY_RUN" == "0" ]]; then
  echo "--- Signing binaries (hardened runtime)..."

  # Sign in correct order: innermost → outermost
  # 3a. Sign all .dylib files
  echo "  Signing .dylib files..."
  find "$APP_PATH" -name "*.dylib" -exec \
    codesign --sign "$IDENTITY" --force --options runtime \
    --entitlements "$ENTITLEMENTS" --timestamp {} \;

  # 3b. Sign all .so files (Python extensions)
  echo "  Signing .so files..."
  find "$APP_PATH" -name "*.so" -exec \
    codesign --sign "$IDENTITY" --force --options runtime \
    --entitlements "$ENTITLEMENTS" --timestamp {} \;

  # 3c. Sign ALL standalone Mach-O executables (catches chrome_crashpad_handler,
  #     ShipIt, torch/bin/protoc, torch_shm_manager, and any other binaries)
  echo "  Signing all Mach-O executables..."
  find "$APP_PATH" -type f -perm +111 | while read -r f; do
    # Check if it's a Mach-O binary (not a script, not already a .dylib/.so/.app/.framework)
    if file "$f" | grep -q "Mach-O"; then
      codesign --sign "$IDENTITY" --force --options runtime \
        --entitlements "$ENTITLEMENTS" --timestamp "$f" 2>/dev/null || true
    fi
  done

  # 3d. Sign all .framework bundles
  echo "  Signing .framework bundles..."
  find "$FRAMEWORKS" -name "*.framework" -maxdepth 1 -exec \
    codesign --sign "$IDENTITY" --force --options runtime --timestamp {} \;

  # 3e. Sign helper apps inside Frameworks
  echo "  Signing helper .app bundles..."
  find "$FRAMEWORKS" -name "*.app" -maxdepth 1 -exec \
    codesign --sign "$IDENTITY" --force --options runtime \
    --entitlements "$ENTITLEMENTS" --timestamp {} \;

  # 3f. Sign the Python binary
  PYTHON_BIN="$RESOURCES/python/venv/bin/python3"
  if [[ -f "$PYTHON_BIN" ]]; then
    echo "  Signing Python binary..."
    codesign --sign "$IDENTITY" --force --options runtime \
      --entitlements "$ENTITLEMENTS" --timestamp "$PYTHON_BIN"
  fi

  # 3g. Sign the outer .app
  echo "  Signing outer Lucid.app..."
  codesign --sign "$IDENTITY" --force --options runtime \
    --entitlements "$ENTITLEMENTS" --timestamp "$APP_PATH"

  # Verify
  echo "  Verifying signature..."
  codesign --verify --deep --strict "$APP_PATH"
  echo "  Signature OK"
else
  echo "--- [DRY RUN] Skipping code signing"
  echo "  Would sign with: $IDENTITY"
  echo "  Entitlements: $ENTITLEMENTS"
fi

# ============ Step 4: Create ZIP (for auto-updates) ============
ZIP_NAME="Lucid-${VERSION}-arm64.zip"
ZIP_PATH="$ROOT/dist/$ZIP_NAME"
echo "--- Creating ZIP for auto-updates..."
cd "$ROOT/dist"
rm -f "$ZIP_NAME"
ditto -c -k --keepParent "Lucid.app" "$ZIP_NAME"
ZIP_SIZE=$(stat -f%z "$ZIP_PATH")
ZIP_SHA512=$(shasum -a 512 "$ZIP_PATH" | awk '{print $1}')
echo "  ZIP: $ZIP_NAME ($ZIP_SIZE bytes)"
cd "$ROOT"

# ============ Step 5: Create DMG (for first-time installs) ============
DMG_NAME="Lucid-${VERSION}.dmg"
DMG_PATH="$ROOT/dist/$DMG_NAME"
echo "--- Creating DMG..."
rm -f "$DMG_PATH"

if [[ "$DRY_RUN" == "0" ]] && command -v create-dmg &>/dev/null; then
  # Create pretty DMG with create-dmg (uses UDZO by default)
  TEMP_DMG_PATH="$ROOT/dist/Lucid-temp.dmg"
  create-dmg \
    --volname "Lucid" \
    --volicon "$ROOT/assets/icon.icns" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "Lucid.app" 175 190 \
    --app-drop-link 425 190 \
    --hide-extension "Lucid.app" \
    "$TEMP_DMG_PATH" \
    "$APP_PATH"
  # Re-compress with LZMA for smaller file size (requires macOS 10.15+)
  echo "  Re-compressing DMG with LZMA..."
  hdiutil convert "$TEMP_DMG_PATH" -format ULMO -o "$DMG_PATH"
  rm -f "$TEMP_DMG_PATH"
else
  # Fallback: simple DMG with LZMA compression
  echo "  [DRY RUN or no create-dmg] Creating simple DMG (LZMA)..."
  hdiutil create -volname "Lucid" -srcfolder "$APP_PATH" \
    -ov -format ULMO "$DMG_PATH"
fi

echo "  DMG: $DMG_NAME"

# ============ Step 6: Notarize ============
if [[ "$DRY_RUN" == "0" ]]; then
  # 6a. Notarize the DMG
  echo "--- Notarizing DMG..."
  xcrun notarytool submit "$DMG_PATH" \
    --keychain-profile "$NOTARY_PROFILE" --wait

  # 6b. Staple the DMG
  echo "--- Stapling notarization ticket to DMG..."
  xcrun stapler staple "$DMG_PATH"

  echo "  Notarization complete"
else
  echo "--- [DRY RUN] Skipping notarization"
fi

# ============ Step 7: Generate latest-mac.yml (update manifest) ============
MANIFEST_PATH="$ROOT/dist/latest-mac.yml"
RELEASE_DATE=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
echo "--- Generating latest-mac.yml..."

cat > "$MANIFEST_PATH" << EOF
version: ${VERSION}
files:
  - url: ${ZIP_NAME}
    sha512: ${ZIP_SHA512}
    size: ${ZIP_SIZE}
path: ${ZIP_NAME}
sha512: ${ZIP_SHA512}
releaseDate: ${RELEASE_DATE}
EOF

echo "  Manifest: latest-mac.yml"

# ============ Step 8: Move app back to Desktop ============
echo "--- Moving Lucid.app back to Desktop..."
rm -rf ~/Desktop/"Lucid.app"
mv "$APP_PATH" ~/Desktop/"Lucid.app"

# ============ Summary ============
echo ""
echo "=== Release Build Complete ==="
echo "  App:      ~/Desktop/Lucid.app"
echo "  DMG:      dist/$DMG_NAME"
echo "  ZIP:      dist/$ZIP_NAME"
echo "  Manifest: dist/latest-mac.yml"
echo ""
echo "To publish:"
echo "  1. Upload ZIP + manifest to R2:"
echo "     wrangler r2 object put lucid-updates/${ZIP_NAME} --file dist/${ZIP_NAME}"
echo "     wrangler r2 object put lucid-updates/latest-mac.yml --file dist/latest-mac.yml --cache-control 'max-age=300'"
echo "  2. Create GitHub release with DMG:"
echo "     gh release create v${VERSION} dist/${DMG_NAME} \\"
echo "       --repo zacharybpoll-cmyk/lucid-releases --title \"Lucid v${VERSION}\""
