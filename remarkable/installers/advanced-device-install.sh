#!/bin/sh
# Exact-device runtime installer. Runs only after host-side archive verification.
set -eu

STAGE=${1:-/tmp/estafette-install}
STATE=/home/root/.local/share/estafette-installer/runtime
ROLLBACK="$STATE/rollback"
created_xovi=0
completed=0
armed=0

restore_runtime() {
    [ "$completed" -eq 1 ] && return 0
    [ "$armed" -eq 1 ] || return 0
    /home/root/xovi/stock >/dev/null 2>&1 || true
    if [ "$created_xovi" -eq 1 ]; then
        rm -rf -- /home/root/xovi
    else
        for relative in xovi.so start debug stock rebuild_hashtable extensions.d/qt-resource-rebuilder.so extensions.d/appload.so; do
            if [ -e "$ROLLBACK/xovi/$relative" ]; then
                mkdir -p "/home/root/xovi/$(dirname "$relative")"
                cp -a "$ROLLBACK/xovi/$relative" "/home/root/xovi/$relative"
            else
                rm -f -- "/home/root/xovi/$relative"
            fi
        done
    fi
    for name in qtfb-shim.so qtfb-shim-32bit.so; do
        if [ -e "$ROLLBACK/shims/$name" ]; then cp -a "$ROLLBACK/shims/$name" "/home/root/shims/$name"; else rm -f -- "/home/root/shims/$name"; fi
    done
    systemctl restart xochitl >/dev/null 2>&1 || true
    echo "Advanced installation failed; stock xochitl and backed-up runtime files were restored." >&2
}
trap restore_runtime EXIT HUP INT TERM

model=$(tr -d '\000' </proc/device-tree/model 2>/dev/null || true)
machine=$(cat /sys/devices/soc0/machine 2>/dev/null || true)
firmware=$(sed -n 's/^IMG_VERSION="\{0,1\}\([^" ]*\)"\{0,1\}$/\1/p' /etc/os-release | head -n1)
arch=$(uname -m)
identity=$machine
[ -n "$identity" ] || identity=$model
echo "$model" | grep -q "Move" \
    && { echo "REFUSED: reMarkable Paper Pro Move is not supported." >&2; exit 30; }
{ [ "$identity" = "reMarkable Ferrari" ] || { echo "$model" | grep -q "Paper Pro" && echo "$model" | grep -vq "Move"; }; } \
    || { echo "REFUSED: advanced installation supports only reMarkable Paper Pro / Ferrari (found $identity)." >&2; exit 30; }
[ "$firmware" = "3.28.0.172" ] \
    || { echo "REFUSED: advanced installation requires OS 3.28.0.172 (found $firmware)." >&2; exit 31; }
[ "$arch" = "aarch64" ] || { echo "REFUSED: Ferrari must report aarch64 (found $arch)." >&2; exit 32; }
systemctl is-active --quiet xochitl || { echo "REFUSED: stock xochitl is not healthy before installation." >&2; exit 33; }

echo "32d64d1262ddc984e3235c7d0340a398fe6d5b3efa6a979865f5977b32630d27  $STAGE/runtime/xovi-aarch64.tar.gz" | sha256sum -c -
echo "29733851d7b6a81e8f7cb754bc122aca5a2e519879c795ebfe0a4625306b108a  $STAGE/runtime/appload-3.28.so" | sha256sum -c -
echo "6df704049aa057ff6374eaaa03a4f4a4d683b7c1ce772920d1a124be74d782c4  $STAGE/runtime/qtfb-shim.so" | sha256sum -c -
echo "aa4fb1e6f2edf5ef0137360cac77713a24ab508800301f81c19c579fee3f5031  $STAGE/runtime/qtfb-shim-32bit.so" | sha256sum -c -
tar -tzf "$STAGE/runtime/xovi-aarch64.tar.gz" | awk '/^\// || /(^|\/)\.\.($|\/)/ || $0 !~ /^xovi\// { bad=1 } END { exit bad }' \
    || { echo "Unsafe Xovi archive." >&2; exit 34; }

rm -rf -- "$ROLLBACK" "$STAGE/runtime/extracted"
mkdir -p "$ROLLBACK/xovi/extensions.d" "$ROLLBACK/shims" "$STAGE/runtime/extracted"
tar -xzf "$STAGE/runtime/xovi-aarch64.tar.gz" -C "$STAGE/runtime/extracted"
[ -f "$STAGE/runtime/extracted/xovi/xovi.so" ] && [ -f "$STAGE/runtime/extracted/xovi/extensions.d/qt-resource-rebuilder.so" ] \
    || { echo "Pinned Xovi archive is incomplete." >&2; exit 35; }

for name in qtfb-shim.so qtfb-shim-32bit.so; do
    [ ! -e "/home/root/shims/$name" ] || cp -a "/home/root/shims/$name" "$ROLLBACK/shims/$name"
done
if [ ! -e /home/root/xovi ]; then
    created_xovi=1
    armed=1
    mkdir -p /home/root/xovi
    cp -a "$STAGE/runtime/extracted/xovi/." /home/root/xovi/
else
    for relative in xovi.so start debug stock rebuild_hashtable extensions.d/qt-resource-rebuilder.so extensions.d/appload.so; do
        if [ -e "/home/root/xovi/$relative" ]; then
            mkdir -p "$ROLLBACK/xovi/$(dirname "$relative")"
            cp -a "/home/root/xovi/$relative" "$ROLLBACK/xovi/$relative"
        fi
    done
    armed=1
    for relative in xovi.so start debug stock rebuild_hashtable extensions.d/qt-resource-rebuilder.so; do
        if [ -e "$STAGE/runtime/extracted/xovi/$relative" ]; then
            mkdir -p "/home/root/xovi/$(dirname "$relative")"
            cp -a "$STAGE/runtime/extracted/xovi/$relative" "/home/root/xovi/$relative"
        fi
    done
fi
mkdir -p /home/root/xovi/extensions.d /home/root/xovi/exthome/appload /home/root/xovi/exthome/qt-resource-rebuilder /home/root/shims
cp "$STAGE/runtime/appload-3.28.so" /home/root/xovi/extensions.d/appload.so
cp "$STAGE/runtime/qtfb-shim.so" /home/root/shims/qtfb-shim.so
cp "$STAGE/runtime/qtfb-shim-32bit.so" /home/root/shims/qtfb-shim-32bit.so
chmod 755 /home/root/xovi/start /home/root/xovi/debug /home/root/xovi/stock /home/root/xovi/rebuild_hashtable
chmod 644 /home/root/xovi/extensions.d/appload.so /home/root/xovi/extensions.d/qt-resource-rebuilder.so /home/root/shims/qtfb-shim.so /home/root/shims/qtfb-shim-32bit.so

/home/root/xovi/rebuild_hashtable
[ -s /home/root/xovi/exthome/qt-resource-rebuilder/hashtab ] || { echo "Hashtable generation failed." >&2; exit 36; }

# This is a one-time health check, not boot persistence. The stock fallback is
# executed immediately if xochitl does not return with Xovi and AppLoad loaded.
setsid /home/root/xovi/start >/tmp/estafette-xovi-start.log 2>&1 </dev/null &
sleep 15
systemctl is-active --quiet xochitl || { echo "xochitl failed its post-patch health check." >&2; exit 37; }
pid=$(pidof xochitl | awk '{print $1}')
[ -n "$pid" ] && tr '\000' '\n' <"/proc/$pid/environ" | grep -q '^LD_PRELOAD=/home/root/xovi/xovi.so$' \
    || { echo "xochitl returned without Xovi; treating the patch as failed." >&2; exit 37; }

completed=1
trap - EXIT HUP INT TERM
echo "Pinned Xovi v19-23052026 and patched AppLoad v0.5.3 passed the xochitl health check."
