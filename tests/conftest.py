import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    # Tests never write the real settings (QSettings -> INI files in a temp folder) or use the real Recycle Bin.
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from pr7du import theme
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    theme.load_fonts()
    yield app
    for w in app.topLevelWidgets():
        w.close()
    app.processEvents()


@pytest.fixture(autouse=True)
def trash(tmp_path, monkeypatch):
    t = tmp_path / "_trash"
    monkeypatch.setenv("PR7DU_TRASH", str(t))
    return t


def make_tree(base: Path) -> dict:
    """A known folder tree: name -> bytes. Video 3 MB, photos, music, a deep chain, an empty folder."""
    files = {
        "Videos/shoot/A001.mov": 3_000_000, "Videos/shoot/A002.mov": 2_000_000, "Videos/export.mp4": 1_500_000,
        "Pictures/2026/DSC_0001.jpg": 400_000, "Pictures/2026/DSC_0002.jpg": 350_000, "Pictures/edit.png": 90_000,
        "Music/album/01 Intro.flac": 600_000, "Music/album/02 Song.flac": 650_000,
        "Docs/notes.txt": 1234, "Docs/deep/a/b/c/d/leaf.bin": 77_777, "setup.exe": 800_000, "readme": 10,
    }
    for name, size in files.items():
        p = base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\0" * size)
    (base / "Empty").mkdir()
    return files


@pytest.fixture
def tree(tmp_path):
    base = tmp_path / "disk"
    base.mkdir()
    return base, make_tree(base)


def _ntfs_tools() -> bool:
    return (sys.platform.startswith("linux") and all(shutil.which(t) for t in ("mkntfs", "ntfs-3g"))
            and os.path.exists("/dev/fuse") and os.geteuid() == 0)


@pytest.fixture
def ntfs_image(tmp_path):
    """A real NTFS volume (mkntfs) holding a known tree, written through ntfs-3g, unmounted: (image, files)."""
    if not _ntfs_tools():
        pytest.skip("needs mkntfs, ntfs-3g and FUSE (Linux)")
    img = tmp_path / "vol.img"
    mnt = tmp_path / "mnt"
    mnt.mkdir()
    with open(img, "wb") as fh:
        fh.truncate(64 << 20)
    subprocess.run(["mkntfs", "-F", "-q", "-f", "-L", "TEST", str(img)], check=True, capture_output=True)
    subprocess.run(["ntfs-3g", str(img), str(mnt)], check=True, capture_output=True)
    try:
        files = make_tree(mnt)
        for i in range(400):                                  # enough records to fill several MFT reads
            p = mnt / "Many" / f"f{i:03d}.dat"
            p.parent.mkdir(exist_ok=True)
            p.write_bytes(b"x" * (i * 37 % 5000))
            files[f"Many/f{i:03d}.dat"] = i * 37 % 5000
        long = "A long name with spaces and ünïcode — over eight-dot-three.txt"
        (mnt / long).write_bytes(b"y" * 4321)
        files[long] = 4321
    finally:
        subprocess.run(["fusermount", "-u", str(mnt)], check=False, capture_output=True) \
            if shutil.which("fusermount") else subprocess.run(["umount", str(mnt)], check=False)
    return img, files


@pytest.fixture
def window(qapp, tree):
    from pr7du.main_window import MainWindow
    w = MainWindow()
    w.sync = True
    w.said = []
    w.answers["say"] = lambda kind, text: w.said.append((kind, text))
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    yield w
    w.close()
