#!/usr/bin/env bash
# =====================================================================
# OpenCodeGoMonitor - Linux 打包脚本 (amd64)
# 生成物: dist/*.deb  +  dist/*.AppImage
# 用法:   ./packaging/build.sh [版本号]     (默认 1.0.2)
#
# 前置:  已激活包含依赖与 PyInstaller 的 venv
#        (python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pyinstaller pillow)
# 可选:  APPIMAGETOOL=/path/to/appimagetool 指定 appimagetool
# =====================================================================
set -euo pipefail

APP_ID="ocgmonitor"                # Debian 包名 / AppImage 图标名
BINARY="ocgmonitor"                # 可执行文件 / usr/bin 命令名
APP_DISPLAY="OpenCode Go 使用记录监控"
DESKTOP_ID="opencode-gomonitor"
DEFAULT_VERSION="1.0.2"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:-$DEFAULT_VERSION}"
ARCH="amd64"
PYINSTALLER_BIN="${PYINSTALLER_BIN:-pyinstaller}"
APPIMAGETOOL="${APPIMAGETOOL:-appimagetool}"
DIST="$ROOT/dist"
DEB_DIR="$ROOT/packaging/deb"

cd "$ROOT"
rm -rf build dist "$ROOT/packaging/appimage/AppDir"
mkdir -p "$DIST"

echo "==> [1/4] PyInstaller 构建 (version=$VERSION)"
"$PYINSTALLER_BIN" --noconfirm --clean --onedir --windowed \
  --name "$BINARY" \
  --icon "$ROOT/packaging/icons/$APP_ID-256.png" \
  --hidden-import matplotlib.backends.backend_qtagg \
  --hidden-import matplotlib.backends.backend_qt5agg \
  --hidden-import PySide6.QtPrintSupport \
  --copy-metadata matplotlib \
  --copy-metadata pandas \
  --copy-metadata numpy \
  --exclude-module tkinter \
  main.py

echo "==> [2/4] 构建 .deb"
PKG_ROOT="$ROOT/packaging/deb-root"
rm -rf "$PKG_ROOT"
mkdir -p "$PKG_ROOT/usr/lib/$APP_ID" \
         "$PKG_ROOT/usr/bin" \
         "$PKG_ROOT/usr/share/applications" \
         "$PKG_ROOT/usr/share/icons/hicolor" \
         "$PKG_ROOT/usr/share/doc/$APP_ID" \
         "$PKG_ROOT/usr/share/man/man1"

# 二进制包体: usr/lib/<app>/ 下放 <binary> 与 _internal/
cp -a "$DIST/$BINARY/$BINARY" "$PKG_ROOT/usr/lib/$APP_ID/$BINARY"
cp -a "$DIST/$BINARY/_internal" "$PKG_ROOT/usr/lib/$APP_ID/_internal"
chmod 755 "$PKG_ROOT/usr/lib/$APP_ID/$BINARY"
# usr/bin 软链
ln -s "../lib/$APP_ID/$BINARY" "$PKG_ROOT/usr/bin/$BINARY"
# 桌面入口
cp "$DEB_DIR/$DESKTOP_ID.desktop" "$PKG_ROOT/usr/share/applications/"
# 图标 (32/48/64/128/256 → hicolor)
for s in 32 48 64 128 256; do
  install -Dm644 "$ROOT/packaging/icons/$APP_ID-$s.png" \
    "$PKG_ROOT/usr/share/icons/hicolor/${s}x${s}/apps/$APP_ID.png"
done
# 文档 / 版权 / 手册
cp "$ROOT/LICENSE" "$PKG_ROOT/usr/share/doc/$APP_ID/copyright" 2>/dev/null || true
printf '%s\n' "$APP_DISPLAY" > "$PKG_ROOT/usr/share/doc/$APP_ID/description.txt"
cat > "$PKG_ROOT/usr/share/man/man1/$BINARY.1" <<'EOF'
.TH OCGMonitor 1
.SH NAME
ocgmonitor \- OpenCode Go usage monitoring desktop app
.SH SYNOPSIS
.B ocgmonitor
.SH DESCRIPTION
OpenCodeGoMonitor fetches opencode.ai usage records and provides a local
PySide6 dashboard with analytics and export.
EOF

# DEBIAN control
CONTROL="$PKG_ROOT/DEBIAN/control"
mkdir -p "$PKG_ROOT/DEBIAN"
sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$ARCH/" -e "s/@PACKAGE@/$APP_ID/" \
    "$DEB_DIR/control" > "$CONTROL"
# postinst
cp "$DEB_DIR/postinst" "$PKG_ROOT/DEBIAN/postinst" && chmod 755 "$PKG_ROOT/DEBIAN/postinst"

# 计算已安装体积 (KB)
INSTALLED=$(du -sk "$PKG_ROOT" | cut -f1)
echo "Installed-Size: $INSTALLED" >> "$CONTROL"

# 生成 .deb (md5sums + 保持权限)
(
  cd "$PKG_ROOT"
  find . -type f ! -path './DEBIAN/*' -exec md5sum {} \; > DEBIAN/md5sums
)
dpkg-deb --root-owner-group --build "$PKG_ROOT" "$DIST/${APP_ID}_${VERSION}_${ARCH}.deb"
rm -rf "$PKG_ROOT"

echo "==> [3/4] 构建 AppImage"
APP_DIR="$ROOT/packaging/appimage/AppDir"
mkdir -p "$APP_DIR/usr/bin" "$APP_DIR/usr/lib/$APP_ID" \
         "$APP_DIR/usr/share/applications" \
         "$APP_DIR/usr/share/icons/hicolor/256x256/apps"
# 与 .deb 相同的布局
cp -a "$DIST/$BINARY/$BINARY" "$APP_DIR/usr/lib/$APP_ID/$BINARY"
cp -a "$DIST/$BINARY/_internal" "$APP_DIR/usr/lib/$APP_ID/_internal"
chmod 755 "$APP_DIR/usr/lib/$APP_ID/$BINARY"
ln -s "../lib/$APP_ID/$BINARY" "$APP_DIR/usr/bin/$BINARY"
cp "$DEB_DIR/$DESKTOP_ID.desktop" "$APP_DIR/usr/share/applications/"
# appimagetool 需要 .desktop 与同名图标位于 AppDir 根目录
cp "$DEB_DIR/$DESKTOP_ID.desktop" "$APP_DIR/$DESKTOP_ID.desktop"
cp "$ROOT/packaging/icons/$APP_ID-256.png" "$APP_DIR/$APP_ID.png"
install -m644 "$ROOT/packaging/icons/$APP_ID-256.png" \
  "$APP_DIR/usr/share/icons/hicolor/256x256/apps/$APP_ID.png"
cp "$ROOT/packaging/appimage/AppRun" "$APP_DIR/AppRun"
chmod 755 "$APP_DIR/AppRun"
ln -sf "$APP_ID.png" "$APP_DIR/.DirIcon"

echo "==> [4/4] 生成 AppImage"
ARCH=x86_64 "$APPIMAGETOOL" "$APP_DIR" \
  "$DIST/${APP_ID}-${VERSION}-x86_64.AppImage"
rm -rf "$APP_DIR"

echo "==> 完成:"
ls -lh "$DIST"/*.deb "$DIST"/*.AppImage
