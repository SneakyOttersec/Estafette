#!/bin/sh
# Runs on the tablet after the host has verified and unpacked the release ZIP.
set -eu

STAGE=${1:-/tmp/estafette-install}
ROOT_PREFIX=${ESTAFETTE_TEST_ROOT:-}
APP_ROOT="$ROOT_PREFIX/home/root/xovi/exthome/appload"
DEST="$APP_ROOT/estafette"
NEW="$APP_ROOT/.estafette-new.$$"
BACKUP_ROOT="$ROOT_PREFIX/home/root/.local/share/estafette-installer"
BACKUP="$BACKUP_ROOT/estafette.previous"
SHORTCUT_ROOT="$ROOT_PREFIX/home/root/xovi/exthome/qt-resource-rebuilder"
completed=0
moved_old=0
switched=0

cleanup() {
    [ "$completed" -eq 1 ] && return 0
    rm -rf -- "$NEW"
    if [ "$switched" -eq 1 ]; then
        rm -rf -- "$DEST"
    fi
    if [ "$moved_old" -eq 1 ] && [ -e "$BACKUP" ]; then
        mv "$BACKUP" "$DEST"
    fi
    echo "Estafette installation failed; the previous app was restored." >&2
}
trap cleanup EXIT HUP INT TERM

[ -x "$ROOT_PREFIX/home/root/xovi/start" ] || { echo "Healthy AppLoad not found: xovi/start is missing." >&2; exit 20; }
[ -f "$ROOT_PREFIX/home/root/xovi/extensions.d/appload.so" ] || { echo "Healthy AppLoad not found: appload.so is missing." >&2; exit 20; }
[ -d "$APP_ROOT" ] || { echo "Healthy AppLoad not found: application directory is missing." >&2; exit 20; }
if [ -z "$ROOT_PREFIX" ]; then
    systemctl is-active --quiet xochitl || { echo "xochitl is not healthy." >&2; exit 21; }
fi
[ -f "$STAGE/estafette/manifest.json" ] && [ -f "$STAGE/estafette/resources.rcc" ] \
    && [ -x "$STAGE/estafette/backend/entry" ] \
    || { echo "The staged AppLoad bundle is incomplete." >&2; exit 22; }
grep -q '"id"[[:space:]]*:[[:space:]]*"estafette"' "$STAGE/estafette/manifest.json" \
    || { echo "The staged AppLoad manifest has the wrong ID." >&2; exit 22; }

model=${ESTAFETTE_DEVICE_MODEL:-$(tr -d '\000' </proc/device-tree/model 2>/dev/null || true)}
machine=${ESTAFETTE_DEVICE_MACHINE:-$(cat /sys/devices/soc0/machine 2>/dev/null || true)}
firmware=${ESTAFETTE_DEVICE_FIRMWARE:-$(sed -n 's/^IMG_VERSION="\{0,1\}\([^" ]*\)"\{0,1\}$/\1/p' /etc/os-release | head -n1)}
identity=$machine
[ -n "$identity" ] || identity=$model
echo "$model" | grep -q "Move" \
    && { echo "REFUSED: reMarkable Paper Pro Move is not supported." >&2; exit 23; }
if [ "$identity" != "reMarkable Ferrari" ] && ! echo "$model" | grep -q "Paper Pro"; then
    echo "REFUSED: Estafette supports only reMarkable Paper Pro / Ferrari (found $identity)." >&2
    exit 23
fi

mkdir -p "$APP_ROOT" "$BACKUP_ROOT"
rm -rf -- "$NEW"
mkdir "$NEW"
cp -a "$STAGE/estafette/." "$NEW/"
chmod 755 "$NEW/backend/entry"
chmod 644 "$NEW/manifest.json" "$NEW/icon.png" "$NEW/resources.rcc"

rm -rf -- "$BACKUP"
if [ -e "$DEST" ]; then
    mv "$DEST" "$BACKUP"
    moved_old=1
fi
mv "$NEW" "$DEST"
switched=1

if { [ "$identity" = "reMarkable Ferrari" ] || echo "$model" | grep -q "Paper Pro"; } \
    && [ "$firmware" = "3.28.0.172" ]; then
    if [ -d "$SHORTCUT_ROOT" ] && [ -s "$SHORTCUT_ROOT/hashtab" ]; then
        cp "$STAGE/installer/shortcut/estafette-sidebar-3.28.qmd" "$SHORTCUT_ROOT/.zz-estafette-sidebar.qmd.$$"
        cp "$STAGE/installer/shortcut/estafette-shortcut.rcc" "$SHORTCUT_ROOT/.estafette-shortcut.rcc.$$"
        chmod 644 "$SHORTCUT_ROOT/.zz-estafette-sidebar.qmd.$$" "$SHORTCUT_ROOT/.estafette-shortcut.rcc.$$"
        mv "$SHORTCUT_ROOT/.estafette-shortcut.rcc.$$" "$SHORTCUT_ROOT/estafette-shortcut.rcc"
        mv "$SHORTCUT_ROOT/.zz-estafette-sidebar.qmd.$$" "$SHORTCUT_ROOT/zz-estafette-sidebar.qmd"
        echo "Installed the separate Estafette sidebar shortcut. Existing Calculator resources were not changed."
    else
        echo "WARNING: App tile installed; sidebar shortcut skipped because the resource-rebuilder hashtable is absent." >&2
    fi
else
    echo "WARNING: App tile installed; sidebar shortcut supports only Ferrari OS 3.28.0.172 (found $identity / $firmware)." >&2
fi

if [ -n "$ROOT_PREFIX" ] && [ "${ESTAFETTE_TEST_FAIL_AFTER_SWITCH:-0}" = 1 ]; then
    exit 29
fi

completed=1
trap - EXIT HUP INT TERM
echo "Estafette installed atomically at $DEST. Cache data in /home/root/.local/share/estafette was preserved."
echo "Open AppLoad and tap Reload. To activate a newly installed sidebar resource, run /home/root/xovi/start."
