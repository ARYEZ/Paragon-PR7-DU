import json
import os

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from pr7du import __version__, app, family, theme
from pr7du.models import NODE


def scanned(window, base):
    window.start_scan(str(base))
    assert window.root is not None and not window.scanning
    return window.root


def test_a_scan_fills_every_view(window, tree):
    base, files = tree
    root = scanned(window, base)
    assert window.how == "walk" and "in 12 files" in window.summary.text()
    top = window.tree_model.index(0, 0)
    assert top.data(NODE) is root and window.tree.isExpanded(top)
    first = window.tree_model.index(0, 0, top)
    assert first.data() == "Videos\\" and first.siblingAtColumn(2).data() == "6.5 MB"
    assert window.files_model.rows[0].name == "A001.mov" and len(window.files_model.rows) == len(files)
    exts = [r[0] for r in window.types_model.rows]
    assert exts[:2] == ["mov", "mp4"]
    assert {t.node.name for t in window.map.tiles} >= {"A001.mov", "readme", "leaf.bin"}


def test_the_map_and_the_tree_follow_each_other(window, tree, qapp):
    base, _ = tree
    root = scanned(window, base)
    tile = next(t for t in window.map.tiles if t.node.name == "leaf.bin")
    QTest.mouseClick(window.map, Qt.MouseButton.LeftButton, pos=QPointF(tile.box.x + tile.box.w / 2,
                                                                        tile.box.y + tile.box.h / 2).toPoint())
    cur = window.tree.currentIndex()
    assert cur.data(NODE) is tile.node and window.map.selected is tile.node
    assert window.where.text() == str(base / "Docs" / "deep" / "a" / "b" / "c" / "d" / "leaf.bin")
    videos = next(c for c in root.children if c.name == "Videos")
    window.tree.setCurrentIndex(window.tree_model.index_of(videos))
    box = window.map.box_of(videos)
    assert window.map.selected is videos and box.width() * box.height() > 0.3 * window.map.width() * window.map.height()
    window.show_view("files")
    window.files.setCurrentIndex(window.files_model.index(1, 0))
    assert window.map.selected.name == "A002.mov"


def test_delete_goes_to_the_recycle_bin_and_shrinks_every_folder(window, tree, trash):
    base, files = tree
    root = scanned(window, base)
    shoot = next(c for c in next(c for c in root.children if c.name == "Videos").children if c.name == "shoot")
    asked = []
    window.answers["delete"] = lambda text: asked.append(text) or True
    before = root.size
    assert window.delete(shoot)
    assert "shoot" in asked[0] and "5.0 MB" in asked[0]
    assert not (base / "Videos" / "shoot").exists() and (trash / "shoot" / "A001.mov").is_file()
    assert root.size == before - 5_000_000 and root.files == len(files) - 2
    videos = next(c for c in root.children if c.name == "Videos")
    assert videos.size == 1_500_000 and [c.name for c in videos.children] == ["export.mp4"]
    assert "A001.mov" not in {n.name for n in window.files_model.rows}
    assert "A001.mov" not in {t.node.name for t in window.map.tiles}
    window.answers["delete"] = False                                 # No: nothing happens
    readme = next(c for c in root.children if c.name == "readme")
    assert not window.delete(readme) and (base / "readme").exists()


def test_menus(window, tree, qapp):
    base, _ = tree
    root = scanned(window, base)
    window.answers["menu"] = True
    m = window.node_menu(root.children[0])
    assert [a.text() for a in m.actions() if a.text()] == ["Open", "Show in folder", "Copy path",
                                                           "Delete (to the Recycle Bin)..."]
    window.copy_path(root.children[0])
    assert qapp.clipboard().text() == str(base / "Videos")
    opened = []
    window.answers["launch"] = lambda appname, args: opened.append((appname, args)) or True
    window.show_in_folder(next(c for c in root.children if c.name == "setup.exe"))
    assert opened == [("PR7-E", [str(base)])]
    m = window.main_menu()
    assert [a.text() for a in m.actions() if a.text()][:3] == ["OBSIDIAN", "AURORA", "Show allocated size"]
    window.show_allocated(True)
    assert not window.tree.isColumnHidden(3)
    window.set_finish("aurora")
    assert theme.FINISH == "aurora" and theme.BACKGROUND in window.styleSheet()
    window.set_finish("obsidian")


def test_cancel_and_family_entry(window, tree):
    base, _ = tree
    window._cancel.set()
    from pr7du import scan
    orig = scan.walk
    try:
        scan.walk = lambda *a, **k: (_ for _ in ()).throw(scan.Cancelled())
        window.start_scan(str(base))
    finally:
        scan.walk = orig
    assert window.summary.text() == "Scan cancelled." and window.scan_button.text() == "SCAN"
    assert family.APPS["PR7-DU"] == "{9DFF1917-658D-4BE5-8C19-A88E7150AC24}"


def test_version(capsys):
    assert app.main(["--version"]) == 0 and capsys.readouterr().out.strip() == __version__


def test_selftest(tree, tmp_path, qapp):
    base, files = tree
    out = tmp_path / "out.json"
    assert app.selftest(str(base), str(out)) == 0
    got = json.loads(out.read_text())
    assert got["size"] == sum(files.values()) and got["files"] == len(files) and got["biggest"][0] == "A001.mov"
    assert got["children"]["Videos"] == 6_500_000 and got["fonts"] and got["tiles"] >= len(files)
