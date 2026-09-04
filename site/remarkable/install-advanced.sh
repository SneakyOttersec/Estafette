#!/bin/sh
# Exact Ferrari 3.28.0.172 bootstrap. All downloads happen on this computer.
set -eu

ORIGIN=${ESTAFETTE_ORIGIN:-https://sneakyottersec.github.io/Estafette}
HOST=root@10.11.99.1
TRIPLETAP=0
for argument in "$@"; do
    case "$argument" in --triple-tap) TRIPLETAP=1 ;; root@[A-Za-z0-9._:-]*) HOST=$argument ;; *) echo "Usage: $0 [root@tablet-address] [--triple-tap]" >&2; exit 2 ;; esac
done
for command in curl python3 tar ssh scp sha256sum; do command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 3; }; done

identity=$(ssh "$HOST" 'printf "model="; tr -d "\000" </proc/device-tree/model 2>/dev/null; printf "\nmachine="; cat /sys/devices/soc0/machine 2>/dev/null; printf "firmware="; sed -n '\''s/^IMG_VERSION="\{0,1\}\([^" ]*\)"\{0,1\}$/\1/p'\'' /etc/os-release | head -n1; printf "arch="; uname -m')
echo "$identity"
echo "$identity" | grep -Eq '^(model=.*Paper Pro.*|machine=reMarkable Ferrari)$' || { echo "REFUSED: not a reMarkable Paper Pro / Ferrari." >&2; exit 10; }
echo "$identity" | grep -q '^model=.*Move' && { echo "REFUSED: Paper Pro Move is not supported." >&2; exit 10; }
echo "$identity" | grep -q '^firmware=3.28.0.172$' || { echo "REFUSED: firmware must be exactly 3.28.0.172." >&2; exit 11; }
echo "$identity" | grep -q '^arch=aarch64$' || { echo "REFUSED: architecture must be aarch64." >&2; exit 12; }

TEMP=$(mktemp -d "${TMPDIR:-/tmp}/estafette-advanced.XXXXXX")
REMOTE=/tmp/estafette-install
trap 'rm -rf -- "$TEMP"' EXIT HUP INT TERM

curl -fsSL --proto '=https' --tlsv1.2 "$ORIGIN/remarkable/app/v1/manifest.json" -o "$TEMP/manifest.json"
python3 - "$TEMP/manifest.json" "$ORIGIN" >"$TEMP/package.env" <<'PY'
import json, shlex, sys
from urllib.parse import urlparse
m = json.load(open(sys.argv[1], encoding="utf-8")); o, p = urlparse(sys.argv[2]), urlparse(m["package_url"])
digest = m.get("sha256", "")
if p.scheme != "https" or p.netloc.lower() != o.netloc.lower(): raise SystemExit("non-same-origin package")
if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest): raise SystemExit("invalid package checksum")
print("PACKAGE_URL=" + shlex.quote(m["package_url"])); print("PACKAGE_SHA256=" + shlex.quote(m["sha256"]))
PY
. "$TEMP/package.env"
curl -fsSL --proto '=https' --tlsv1.2 "$PACKAGE_URL" -o "$TEMP/estafette.zip"
printf '%s  %s\n' "$PACKAGE_SHA256" "$TEMP/estafette.zip" | sha256sum -c -
python3 - "$TEMP/estafette.zip" "$TEMP/package" <<'PY'
import pathlib, stat, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    for item in archive.infolist():
        path = pathlib.PurePosixPath(item.filename); mode = item.external_attr >> 16
        if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(mode):
            raise SystemExit("unsafe package archive member: " + item.filename)
    archive.extractall(sys.argv[2])
PY
mkdir -p "$TEMP/package/runtime"

curl -fL --proto '=https' --tlsv1.2 \
  https://github.com/asivery/rm-xovi-extensions/releases/download/v19-23052026/xovi-aarch64.tar.gz \
  -o "$TEMP/package/runtime/xovi-aarch64.tar.gz"
printf '%s  %s\n' 32d64d1262ddc984e3235c7d0340a398fe6d5b3efa6a979865f5977b32630d27 "$TEMP/package/runtime/xovi-aarch64.tar.gz" | sha256sum -c -
curl -fL --proto '=https' --tlsv1.2 \
  https://github.com/asivery/rm-appload/releases/download/v0.5.3/appload-aarch64.zip \
  -o "$TEMP/appload.zip"
printf '%s  %s\n' 032e3f2c57a004aba4425894758e4b542c67590efd222e3b3d5141124c45e84d "$TEMP/appload.zip" | sha256sum -c -
python3 - "$TEMP/appload.zip" "$TEMP/appload" <<'PY'
import pathlib, stat, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    for item in archive.infolist():
        path = pathlib.PurePosixPath(item.filename); mode = item.external_attr >> 16
        if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(mode):
            raise SystemExit("unsafe AppLoad archive member: " + item.filename)
    archive.extractall(sys.argv[2])
PY
printf '%s  %s\n' 31214cbbe64c8bfe7d99096f077c3009dba8a42ef1a733801aa0ec59c134e7cc "$TEMP/appload/appload.so" | sha256sum -c -
python3 "$TEMP/package/installer/patch_appload_3_28.py" \
  "$TEMP/appload/appload.so" "$TEMP/package/runtime/appload-3.28.so" \
  --compat "$TEMP/package/installer/compat"
printf '%s  %s\n' 29733851d7b6a81e8f7cb754bc122aca5a2e519879c795ebfe0a4625306b108a "$TEMP/package/runtime/appload-3.28.so" | sha256sum -c -
cp "$TEMP/appload/shims/qtfb-shim.so" "$TEMP/appload/shims/qtfb-shim-32bit.so" "$TEMP/package/runtime/"

if [ "$TRIPLETAP" -eq 1 ]; then
    curl -fL --proto '=https' --tlsv1.2 \
      https://github.com/rmitchellscott/xovi-tripletap/archive/869497aa61435448bf0077fbf75fb264dcba92c5.tar.gz \
      -o "$TEMP/tripletap.tar.gz"
    tar -tzf "$TEMP/tripletap.tar.gz" | awk '/^\// || /(^|\/)\.\.($|\/)/ { bad=1 } END { exit bad }' \
      || { echo "Unsafe triple-tap archive." >&2; exit 40; }
    tar -xzf "$TEMP/tripletap.tar.gz" -C "$TEMP/package"
    tripletap_dir=$(find "$TEMP/package" -maxdepth 1 -type d -name 'xovi-tripletap-*' | head -n1)
    printf '%s  %s\n' c84f0c441118078a74bf3a7e1ee9aa136ab1fed3cc43668637a97a3cd0cddfa2 "$tripletap_dir/install.sh" | sha256sum -c -
    mv "$tripletap_dir" "$TEMP/package/tripletap"
fi

chmod 755 "$TEMP/package/estafette/backend/entry" "$TEMP/package/installer/"*.sh
ssh "$HOST" "rm -rf -- '$REMOTE' && mkdir -p '$REMOTE'"
scp -q -r "$TEMP/package/." "$HOST:$REMOTE/"
ssh "$HOST" "sh '$REMOTE/installer/advanced-device-install.sh' '$REMOTE'"
ssh "$HOST" "sh '$REMOTE/installer/device-install.sh' '$REMOTE'"

if [ "$TRIPLETAP" -eq 1 ]; then
    ssh "$HOST" "set -eu; d=/home/root/xovi-tripletap; mkdir -p \"\$d\"; if [ -f \"\$d/config\" ]; then cp \"\$d/config\" /tmp/estafette-tripletap-config; fi; cp -a '$REMOTE/tripletap/.' \"\$d/\"; [ ! -f /tmp/estafette-tripletap-config ] || mv /tmp/estafette-tripletap-config \"\$d/config\"; cp \"\$d/evtest.arm64\" \"\$d/evtest\"; chmod 755 \"\$d\"/*.sh \"\$d/evtest\"; [ -f \"\$d/config\" ] || { cp \"\$d/config.default\" \"\$d/config\"; }; \"\$d/enable.sh\""
    echo "Optional triple-tap persistence installed from reviewed revision 869497aa61435448bf0077fbf75fb264dcba92c5."
fi
ssh "$HOST" "rm -rf -- '$REMOTE'"
echo "Advanced installation complete. No password, notebook, xochitl unit, or automatic Xovi boot injection was installed."
