"""Build and open the Sovereign Local macOS menu bar app."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import PROJECT_ROOT

APP_NAME = "Sovereign Local.app"
BUNDLE_ID = "com.sovereign.localbar"

INFO = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Sovereign Local</string>
  <key>CFBundleDisplayName</key><string>Sovereign Local</string>
  <key>CFBundleIdentifier</key><string>{bundle}</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>LocalBar</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
</dict>
</plist>
"""


def app_path() -> Path:
    return Path.home() / "Applications" / APP_NAME


def source_path() -> Path:
    return PROJECT_ROOT / "tools" / "LocalBar.swift"


def install() -> Path:
    """Compile the Swift menu bar app and place it in ~/Applications."""
    source = source_path()
    if not source.is_file():
        raise FileNotFoundError(f"missing {source}")
    app = app_path()
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    (app / "Contents" / "Info.plist").write_text(INFO.format(bundle=BUNDLE_ID), encoding="utf-8")
    binary = macos / "LocalBar"
    subprocess.run(
        [
            "swiftc",
            "-O",
            "-swift-version",
            "5",
            "-framework",
            "Cocoa",
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(app)],
        check=False,
        capture_output=True,
        text=True,
    )
    return app


def open_app() -> None:
    app = app_path()
    if not app.is_dir():
        install()
    subprocess.run(["open", str(app)], check=False)


def running() -> bool:
    result = subprocess.run(
        ["pgrep", "-f", f"{APP_NAME}/Contents/MacOS/LocalBar"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())
