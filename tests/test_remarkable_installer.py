import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def staged_bundle(root: Path, version: str) -> Path:
    bundle = root / "package-root" / "estafette"
    (bundle / "backend").mkdir(parents=True, exist_ok=True)
    (bundle / "manifest.json").write_text(
        json.dumps({"id": "estafette", "loadsBackend": True, "version": version})
    )
    (bundle / "icon.png").write_bytes(b"png")
    (bundle / "resources.rcc").write_bytes(b"rcc")
    entry = bundle / "backend/entry"
    entry.write_bytes(b"binary-" + version.encode())
    entry.chmod(0o755)
    installer = root / "package-root/installer"
    (installer / "shortcut").mkdir(parents=True, exist_ok=True)
    (installer / "shortcut/estafette-sidebar-3.28.qmd").write_text("qmd")
    (installer / "shortcut/estafette-shortcut.rcc").write_bytes(b"shortcut")
    return bundle


def test_package_is_deterministic_and_manifest_verification_rejects_missing_file(
    tmp_path,
):
    bundle = staged_bundle(tmp_path, "test")
    overlay = tmp_path / "overlay"
    command = [
        "python",
        ROOT / "src/package_remarkable_app.py",
        "--bundle",
        bundle,
        "--overlay",
        overlay,
        "--version",
        "test",
        "--origin",
        "https://example.test",
    ]
    subprocess.run(command, check=True)
    archive = overlay / "remarkable/downloads/estafette-rmpp-test.zip"
    first = hashlib.sha256(archive.read_bytes()).hexdigest()
    subprocess.run(command, check=True)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == first
    (bundle / "resources.rcc").unlink()
    assert subprocess.run(command, capture_output=True, check=False).returncode != 0


def test_device_installer_refuses_without_appload_and_is_atomic_idempotent(tmp_path):
    device = tmp_path / "device"
    stage = tmp_path / "stage"
    staged_bundle(stage, "one")
    script = ROOT / "remarkable/installers/device-install.sh"
    env = {
        **os.environ,
        "ESTAFETTE_TEST_ROOT": str(device),
        "ESTAFETTE_DEVICE_MACHINE": "reMarkable Ferrari",
        "ESTAFETTE_DEVICE_MODEL": "reMarkable Paper Pro",
        "ESTAFETTE_DEVICE_FIRMWARE": "3.28.0.172",
    }
    refused = subprocess.run(
        ["sh", script, stage / "package-root"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert refused.returncode == 20 and "Healthy AppLoad not found" in refused.stderr

    xovi = device / "home/root/xovi"
    (xovi / "extensions.d").mkdir(parents=True)
    (xovi / "exthome/appload").mkdir(parents=True)
    (xovi / "exthome/qt-resource-rebuilder").mkdir(parents=True)
    (xovi / "start").write_text("#!/bin/sh\n")
    (xovi / "start").chmod(0o755)
    (xovi / "extensions.d/appload.so").write_bytes(b"appload")
    (xovi / "exthome/qt-resource-rebuilder/hashtab").write_bytes(b"hash")
    cache = device / "home/root/.local/share/estafette/cache-marker"
    cache.parent.mkdir(parents=True)
    cache.write_text("keep")

    wrong_device = subprocess.run(
        ["sh", script, stage / "package-root"],
        env={
            **env,
            "ESTAFETTE_DEVICE_MACHINE": "reMarkable Zero Sugar",
            "ESTAFETTE_DEVICE_MODEL": "reMarkable 2",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert wrong_device.returncode == 23 and "Paper Pro" in wrong_device.stderr

    subprocess.run(["sh", script, stage / "package-root"], env=env, check=True)
    installed = xovi / "exthome/appload/estafette/backend/entry"
    assert installed.read_bytes() == b"binary-one"
    assert (xovi / "exthome/qt-resource-rebuilder/zz-estafette-sidebar.qmd").is_file()
    assert cache.read_text() == "keep"

    staged_bundle(stage, "two")
    subprocess.run(["sh", script, stage / "package-root"], env=env, check=True)
    assert installed.read_bytes() == b"binary-two"
    backup = (
        device
        / "home/root/.local/share/estafette-installer/estafette.previous/backend/entry"
    )
    assert backup.read_bytes() == b"binary-one"

    staged_bundle(stage, "broken")
    failed_env = {**env, "ESTAFETTE_TEST_FAIL_AFTER_SWITCH": "1"}
    assert (
        subprocess.run(
            ["sh", script, stage / "package-root"], env=failed_env, check=False
        ).returncode
        != 0
    )
    assert installed.read_bytes() == b"binary-two"


def test_advanced_installer_has_exact_gates_hashes_health_rollback_and_opt_in_persistence():
    advanced = (ROOT / "site/remarkable/install-advanced.sh").read_text()
    device = (ROOT / "remarkable/installers/advanced-device-install.sh").read_text()
    shortcut = (ROOT / "remarkable/shortcut/estafette-sidebar-3.28.qmd").read_text()
    assert "3.28.0.172" in advanced and "Paper Pro Move is not supported" in advanced
    assert (
        "32d64d1262ddc984e3235c7d0340a398fe6d5b3efa6a979865f5977b32630d27" in advanced
    )
    assert (
        "032e3f2c57a004aba4425894758e4b542c67590efd222e3b3d5141124c45e84d" in advanced
    )
    assert (
        "c84f0c441118078a74bf3a7e1ee9aa136ab1fed3cc43668637a97a3cd0cddfa2" in advanced
    )
    assert (
        "--triple-tap" in advanced
        and "systemctl" not in (ROOT / "site/remarkable/install-safe.sh").read_text()
    )
    assert "restore_runtime" in device and "/home/root/xovi/stock" in device
    assert '[ "$armed" -eq 1 ] || return 0' in device
    assert "systemctl is-active --quiet xochitl" in device
    assert 'requestLaunch("estafette"' in shortcut
    assert "Calculator" not in shortcut
