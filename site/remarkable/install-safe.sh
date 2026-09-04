#!/bin/sh
# Host-side installer for tablets that already have a healthy AppLoad.
set -eu

ORIGIN=${ESTAFETTE_ORIGIN:-https://sneakyottersec.github.io/Estafette}
HOST=${1:-root@10.11.99.1}
case "$HOST" in root@[A-Za-z0-9._:-]*) ;; *) echo "Usage: $0 [root@tablet-address]" >&2; exit 2 ;; esac
for command in curl python3 ssh scp sha256sum; do command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 3; }; done

TEMP=$(mktemp -d "${TMPDIR:-/tmp}/estafette-safe.XXXXXX")
REMOTE=/tmp/estafette-install
trap 'rm -rf -- "$TEMP"' EXIT HUP INT TERM

curl -fsSL --proto '=https' --tlsv1.2 "$ORIGIN/remarkable/app/v1/manifest.json" -o "$TEMP/manifest.json"
python3 - "$TEMP/manifest.json" "$ORIGIN" >"$TEMP/package.env" <<'PY'
import json, shlex, sys
from urllib.parse import urlparse
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
origin, package = urlparse(sys.argv[2]), urlparse(manifest["package_url"])
if package.scheme != "https" or package.netloc.lower() != origin.netloc.lower():
    raise SystemExit("refusing a non-same-origin package URL")
digest = manifest.get("sha256", "")
if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
    raise SystemExit("invalid package checksum")
print("PACKAGE_URL=" + shlex.quote(manifest["package_url"]))
print("PACKAGE_SHA256=" + shlex.quote(digest))
PY
. "$TEMP/package.env"
curl -fsSL --proto '=https' --tlsv1.2 "$PACKAGE_URL" -o "$TEMP/estafette.zip"
printf '%s  %s\n' "$PACKAGE_SHA256" "$TEMP/estafette.zip" | sha256sum -c -
python3 - "$TEMP/estafette.zip" "$TEMP/package" <<'PY'
import pathlib, stat, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    for item in archive.infolist():
        path = pathlib.PurePosixPath(item.filename)
        mode = item.external_attr >> 16
        if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(mode):
            raise SystemExit("unsafe package archive member: " + item.filename)
    archive.extractall(sys.argv[2])
PY
[ -x "$TEMP/package/estafette/backend/entry" ] || chmod 755 "$TEMP/package/estafette/backend/entry"
[ -x "$TEMP/package/installer/device-install.sh" ] || chmod 755 "$TEMP/package/installer/device-install.sh"

ssh "$HOST" "rm -rf -- '$REMOTE' && mkdir -p '$REMOTE'"
scp -q -r "$TEMP/package/estafette" "$TEMP/package/installer" "$HOST:$REMOTE/"
ssh "$HOST" "sh '$REMOTE/installer/device-install.sh' '$REMOTE'"
ssh "$HOST" "rm -rf -- '$REMOTE'"
echo "Safe installation complete. No runtime, notebook, password, or boot configuration was changed."
