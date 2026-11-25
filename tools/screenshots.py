"""Screenshots of the real PR7-DU window on a made-up C: drive (no disk is read):
QT_SCALE_FACTOR=2 python tools/screenshots.py OUT_DIR"""
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())     # not the real ones

from pr7du import theme  # noqa: E402
from pr7du.main_window import MainWindow  # noqa: E402
from pr7du.scan import Node, finish  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
rnd = random.Random(7)
GB, MB = 1e9, 1e6
T0 = 1_764_000_000


def f(name, size):
    return Node(name, int(size), -(-int(size) // 4096) * 4096, T0 + rnd.randint(0, 2_000_000))


def d(name, *kids):
    n = Node(name, is_dir=True)
    for k in kids:
        n.add(k)
    return n


def many(prefix, ext, n, lo, hi):
    return [f(f"{prefix}{i:04d}.{ext}", rnd.uniform(lo, hi)) for i in range(n)]


def mixed(n, exts, lo, hi):
    return [f(f"file{i:03d}.{rnd.choice(exts)}", rnd.uniform(lo, hi)) for i in range(n)]


C = d("C:\\",
      d("Users", d("me",
        d("Videos", d("Elseworld shoot", *many("A001_C", "mov", 14, 1.2 * GB, 4.6 * GB)),
          d("Exports", *many("Elseworld_v", "mp4", 9, 300 * MB, 1.4 * GB))),
        d("Pictures", d("2026", *many("DSC_", "nef", 180, 25 * MB, 32 * MB)), d("Edits", *many("DSC_", "jpg", 120, 4 * MB, 12 * MB))),
        d("Music", *[d(f"Album {i}", *many("track", "flac", 12, 20 * MB, 45 * MB)) for i in range(14)]),
        d("Downloads", *mixed(40, ["zip", "exe", "msi", "iso", "pdf", "7z"], 2 * MB, 900 * MB)),
        d("Documents", *mixed(90, ["pdf", "docx", "xlsx", "txt"], 0.1 * MB, 18 * MB)),
        d("AppData", d("Local", *mixed(60, ["db", "dat", "bin", "log", "dll"], 1 * MB, 400 * MB)),
          d("Roaming", *mixed(50, ["json", "db", "dll", "exe"], 0.2 * MB, 80 * MB))))),
      d("Windows", d("System32", *mixed(160, ["dll", "exe", "sys", "mui"], 0.5 * MB, 60 * MB)),
        d("WinSxS", *mixed(140, ["dll", "cab", "exe"], 2 * MB, 120 * MB)), d("Installer", *mixed(30, ["msi", "msp"], 20 * MB, 400 * MB))),
      d("Program Files", *[d(n, *mixed(24, ["exe", "dll", "pak", "dat"], 1 * MB, 300 * MB))
                           for n in ("Blender Foundation", "DaVinci Resolve", "Steam", "Adobe", "Mozilla")]),
      d("Program Files (x86)", *mixed(60, ["exe", "dll"], 0.5 * MB, 40 * MB)),
      f("pagefile.sys", 12.8 * GB), f("hiberfil.sys", 6.4 * GB), f("swapfile.sys", 0.27 * GB))
finish(C)


def window():
    w = MainWindow()
    w.sync = True
    w.resize(1280, 860)
    w.drive.clear()
    w.drive.addItem("C:  WINDOWS  ·  476.9 GB  ·  164.2 GB FREE", "C:\\")
    w.admin_button.hide()
    w.show()
    w.set_tree(C)
    w.how = "mft"
    from pr7du.models import human
    w.summary.setText(f"{human(C.size)} in {C.files:,} files  ·  scanned in 3.8 s  (the drive's own index)")
    app.processEvents()
    return w


def go(w, *names):
    n = C
    for name in names:
        n = next(c for c in n.children if c.name == name)
    w.reveal(n)
    app.processEvents()
    return n


def shoot(w, name):
    app.processEvents()
    w.grab().save(str(out / name))
    print(out / name)


w = window()
shoot_dir = go(w, "Users", "me", "Videos", "Elseworld shoot")
clip = shoot_dir.children[3]
box = w.map.box_of(clip)
w.map.mouseMoveEvent(type("E", (), {"position": lambda self: QPointF(box.center())})())
shoot(w, "tree.png")
w.show_view("files")
w.files.setCurrentIndex(w.files_model.index(2, 0))
shoot(w, "files.png")
w.close()
w = window()
w.set_finish("aurora")
go(w, "Users", "me", "Videos", "Elseworld shoot")
shoot(w, "tree_aurora.png")
w.set_finish("obsidian")
w.close()
