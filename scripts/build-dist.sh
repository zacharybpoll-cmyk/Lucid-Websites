#!/usr/bin/env bash
# build-dist.sh — Distribution build for Lucid
# Creates an optimized .app bundle with minimal size (~2.4GB target)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Lucid Distribution Build ==="
echo "Root: $ROOT"

# 1. Kill any running Lucid processes
echo "--- Killing existing Lucid processes..."
pkill -f "Lucid" 2>/dev/null || true
sleep 1

# 2. Create clean python-dist by copying python/ excluding unnecessary files
echo "--- Creating clean python-dist/..."
rm -rf python-dist
rsync -a --progress python/ python-dist/ \
  --exclude='tests/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache/' \
  --exclude='*.dist-info/'

# 2b. Fix venv symlinks — replace with actual binary + relative links
echo "--- Fixing venv python symlinks..."
VENV_BIN="python-dist/venv/bin"
if [ -d "$VENV_BIN" ]; then
  # Resolve the actual Python binary (follow all symlinks)
  REAL_PYTHON="$(readlink -f python/venv/bin/python3)"
  echo "  Real python: $REAL_PYTHON"
  # Remove broken symlinks, copy actual binary, create relative links
  rm -f "$VENV_BIN/python" "$VENV_BIN/python3" "$VENV_BIN/python3.13"
  cp "$REAL_PYTHON" "$VENV_BIN/python3"
  ln -s python3 "$VENV_BIN/python"
  ln -s python3 "$VENV_BIN/python3.13"
  echo "  Venv python fixed: $(file "$VENV_BIN/python3")"
fi

# 3. Strip unnecessary packages from venv site-packages
echo "--- Stripping unnecessary packages from venv..."
SITE_PACKAGES=$(find python-dist -type d -name "site-packages" | head -1)
if [ -n "$SITE_PACKAGES" ]; then
  echo "  Site-packages: $SITE_PACKAGES"

  # Remove unused large packages
  for pkg in onnxruntime pip setuptools _pytest pytest pygments pkg_resources; do
    if [ -d "$SITE_PACKAGES/$pkg" ]; then
      echo "  Removing $pkg..."
      rm -rf "$SITE_PACKAGES/$pkg"
    fi
  done

  # Strip PyTorch test/debug files
  TORCH_DIR="$SITE_PACKAGES/torch"
  if [ -d "$TORCH_DIR" ]; then
    echo "  Stripping torch test/include/distributed..."
    rm -rf "$TORCH_DIR/test" "$TORCH_DIR/include" 2>/dev/null || true
    find "$TORCH_DIR" -name "_C/_distributed*" -delete 2>/dev/null || true
    find "$TORCH_DIR" -name "*.pdb" -delete 2>/dev/null || true
  fi

  # Strip dist-info directories
  find "$SITE_PACKAGES" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true

  # Strip __pycache__ from site-packages
  find "$SITE_PACKAGES" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
fi

# 4. Strip __pycache__ and .pyc from python-dist top-level too
find python-dist -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find python-dist -name "*.pyc" -delete 2>/dev/null || true

# 5. Report python-dist size
DIST_SIZE=$(du -sh python-dist | cut -f1)
echo "  python-dist size: $DIST_SIZE"

# 6. Run electron-packager with python-dist as extra resource
echo "--- Running electron-packager..."
npx electron-packager . "Lucid" --platform=darwin --arch=arm64 \
  --icon=assets/icon.icns --app-bundle-id=com.electron.lucid \
  --app-version=1.0.0 --extra-resource=python-dist \
  --ignore='^/python$' --ignore='^/python/' \
  --ignore='^/python-dist$' --ignore='^/python-dist/' \
  --ignore='^/\.pytest_cache' --ignore='^/claude-dashboard' \
  --ignore='^/build$' --ignore='^/build/' \
  --ignore='^/dist$' --ignore='^/dist/' \
  --ignore='^/tasks$' --ignore='^/tasks/' \
  --ignore='^/scripts$' --ignore='^/scripts/' \
  --ignore='^/CLAUDE\.md$' --ignore='^/Lucid_' --ignore='^/~\$' \
  --ignore='^/Screenshot' --ignore='^/first-breath-preview\.html$' \
  --ignore='^/Lucid-darwin-arm64$' --ignore='^/Lucid-darwin-arm64/' \
  --ignore='^/lucid-website$' --ignore='^/lucid-website/' \
  --ignore='\.zip$' --ignore='\.docx$' --ignore='\.pdf$' \
  --ignore='^/Claude_Code' --ignore='^/README-INSTALL' \
  --ignore='^/Vision Care' --ignore='^/lucid_assessment' \
  --ignore='^/\.git$' --ignore='^/\.git/' \
  --overwrite

# 7. Rename python-dist -> python inside the .app bundle
APP_BUNDLE="./Lucid-darwin-arm64/Lucid.app"
RESOURCES="$APP_BUNDLE/Contents/Resources"
if [ -d "$RESOURCES/python-dist" ]; then
  echo "--- Renaming python-dist -> python in app bundle..."
  mv "$RESOURCES/python-dist" "$RESOURCES/python"
fi

# 7b. Fix venv symlinks inside the app bundle (electron-packager converts relative → absolute)
echo "--- Fixing venv symlinks in app bundle..."
BUNDLE_VENV_BIN="$RESOURCES/python/venv/bin"
if [ -d "$BUNDLE_VENV_BIN" ]; then
  rm -f "$BUNDLE_VENV_BIN/python" "$BUNDLE_VENV_BIN/python3.13"
  ln -s python3 "$BUNDLE_VENV_BIN/python"
  ln -s python3 "$BUNDLE_VENV_BIN/python3.13"
  echo "  Fixed: python → python3, python3.13 → python3"
  ls -la "$BUNDLE_VENV_BIN"/python* 2>&1
fi

# 8. Final cleanup inside the app bundle
echo "--- Final cleanup inside app bundle..."
find "$RESOURCES/python" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$RESOURCES/python" -type d -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
find "$RESOURCES/python" -name "*.pyc" -delete 2>/dev/null || true

# 9. Move to Desktop
echo "--- Moving to Desktop..."
rm -rf ~/Desktop/"Lucid.app"
mv "$APP_BUNDLE" ~/Desktop/"Lucid.app"

# 10. Clean up
echo "--- Cleaning up..."
rm -rf python-dist
rm -rf "./Lucid-darwin-arm64"

# 11. Report final size
FINAL_SIZE=$(du -sh ~/Desktop/"Lucid.app" | cut -f1)
echo ""
echo "=== Build Complete ==="
echo "  Location: ~/Desktop/Lucid.app"
echo "  Size: $FINAL_SIZE"
echo ""
echo "To create ZIP for distribution:"
echo "  cd ~/Desktop && zip -r -9 'Lucid-v1.0.0-arm64.zip' 'Lucid.app'"
