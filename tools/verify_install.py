"""Check a real install of PR7-DU-Setup.exe (CI, Windows): python tools/verify_install.py installed|uninstalled

`installed` runs the installed PR7-DU.exe --selftest twice: on a folder made here with known sizes (the folder walk),
and on the runner's whole system drive, which CI reads with administrator rights through its MFT, so the frozen
program is shown to read NTFS directly. `uninstalled` checks it's gone."""
import json
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

HKCU = winreg.HKEY_CURRENT_USER
APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PR7-DU"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Paragon PR7-DU.lnk"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{9DFF1917-658D-4BE5-8C19-A88E7150AC24}_is1"


def value(path, name=""):
    try:
        with winreg.OpenKey(HKCU, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def check(ok, what, p):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        p.append(what)


def selftest(target: str, timeout: int) -> dict:
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.json"
        t = time.monotonic()
        subprocess.run([str(APP / "PR7-DU.exe"), "--selftest", target, str(out)], timeout=timeout, check=False)
        got = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        got["seconds"] = round(time.monotonic() - t, 1)
        return got


def installed():
    p = []
    exe = APP / "PR7-DU.exe"
    for f in (exe, APP / "unins000.exe", APP / "_internal" / "pr7du" / "fonts" / "Inter-Regular.ttf",
              APP / "_internal" / "pr7du" / "icons" / "app.ico"):
        check(f.is_file(), f"file {f}", p)
    check(SHORTCUT.is_file(), "Start menu shortcut", p)
    check(value(UNINSTALL, "DisplayName") == "Paragon PR7-DU", "Installed apps entry", p)
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "known"
        sizes = {"Videos/a.mov": 3_000_000, "Videos/b.mp4": 1_000_000, "Docs/n.txt": 1234, "x.bin": 500}
        for rel, n in sizes.items():
            f = base / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"\0" * n)
        got = selftest(str(base), 120)
        check(got.get("size") == sum(sizes.values()) and got.get("files") == 4 and got.get("how") == "walk",
              f"a folder scanned ({got})", p)
        check(got.get("children", {}).get("Videos") == 4_000_000 and got.get("biggest", [""])[0] == "a.mov",
              "folder totals and the biggest file", p)
        check(got.get("fonts") is True and got.get("tiles", 0) >= 4, "Inter fonts and the map", p)
    drive = os.environ.get("SystemDrive", "C:") + "\\"
    got = selftest(drive, 900)
    check(got.get("how") == "mft" and got.get("files", 0) > 10_000,
          f"{drive} read through its MFT: {got.get('files', 0):,} files, {got.get('size', 0) / 1e9:.1f} GB "
          f"in {got.get('seconds')} s ({got.get('how') or got.get('error')})", p)
    return p


def uninstalled():
    deadline = time.time() + 60
    while True:
        p = []
        check(not (APP / "PR7-DU.exe").exists(), "program files removed", p)
        check(not SHORTCUT.exists(), "Start menu shortcut removed", p)
        check(value(UNINSTALL, "DisplayName") is None, "Installed apps entry removed", p)
        if not p or time.time() > deadline:
            return p
        print("... waiting for the uninstaller to finish")
        time.sleep(3)


if __name__ == "__main__":
    problems = {"installed": installed, "uninstalled": uninstalled}[sys.argv[1]]()
    print("\nALL OK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
