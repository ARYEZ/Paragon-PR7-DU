import os
import sys

import pytest

from pr7du import kinds, mft, scan, treemap
from pr7du.treemap import Box


def find(root, rel):
    n = root
    for part in rel.split("/"):
        n = next(c for c in n.children if c.name == part)
    return n


def files_of(root, prefix=""):
    out = {}
    for c in root.children:
        rel = f"{prefix}{c.name}"
        if c.is_dir:
            out.update(files_of(c, rel + "/"))
        else:
            out[rel] = c.size
    return out


# ---------------------------------------------------------------- the treemap
def test_squarify_matches_the_papers_example():
    boxes = treemap.squarify([6, 6, 4, 3, 2, 2, 1], Box(0, 0, 6, 4))
    shapes = [(round(b.x, 2), round(b.y, 2), round(b.w, 2), round(b.h, 2)) for b in boxes]
    assert shapes[:2] == [(0, 0, 3, 2), (0, 2, 3, 2)]           # the two 6s: a column of squares-ish
    assert abs(sum(b.area for b in boxes) - 24) < 1e-9
    for b, size in zip(boxes, [6, 6, 4, 3, 2, 2, 1]):
        assert abs(b.area - size) < 1e-9                        # area = size
    assert max(max(b.w / b.h, b.h / b.w) for b in boxes) < 3


def test_squarify_keeps_order_and_ignores_zeros():
    boxes = treemap.squarify([1, 0, 5, 2], Box(10, 10, 100, 50))
    assert boxes[1].area == 0 and boxes[2].area > boxes[3].area > boxes[0].area
    for b in boxes:
        assert 10 <= b.x and b.x + b.w <= 110.0001 and 10 <= b.y and b.y + b.h <= 60.0001


def test_layout_nests_folders_and_finds_tiles(tree):
    base, files = tree
    root = scan.walk(str(base))
    tiles = treemap.layout(root, Box(0, 0, 800, 500), inset=1.5)
    names = {t.node.name for t in tiles}
    assert "A001.mov" in names and "readme" in names
    big = next(t for t in tiles if t.node.name == "A001.mov")
    assert treemap.tile_at(tiles, big.box.x + 1, big.box.y + 1).node is big.node
    share = big.box.area / (800 * 500)
    assert abs(share - 3_000_000 / root.size) < 0.02                # its share of the map is its share of the disk


def test_kinds():
    assert kinds.ext_of("Movie.Final.MKV") == "mkv" and kinds.ext_of(".bashrc") == "" and kinds.ext_of("README") == ""
    assert kinds.kind_of("a.mov") == "video" and kinds.kind_of("x.dll") == "program" and kinds.kind_of("q.zzz") == "other"
    for colour, _ in kinds.KINDS.values():                          # the family's colours only
        from PySide6.QtGui import QColor
        c = QColor(colour)
        hue, sat = c.hslHue(), c.hslSaturation()
        assert sat < 30 or hue >= 300 or hue <= 45, colour


# ---------------------------------------------------------------- the folder walk
def test_walk_totals(tree):
    base, files = tree
    seen = []
    root = scan.walk(str(base), progress=seen.append, every=0)
    assert files_of(root) == files
    assert root.size == sum(files.values()) and root.files == len(files)
    assert root.folders == 13                                        # every folder below, the empty one included
    shoot = find(root, "Videos/shoot")
    assert shoot.size == 5_000_000 and shoot.files == 2 and shoot.path() == str(base / "Videos" / "shoot")
    assert [c.name for c in root.children][:4] == ["Videos", "Music", "Pictures", "setup.exe"]     # largest first
    assert seen and seen[-1].files == len(files) and seen[-1].bytes == root.size


@pytest.mark.skipif(sys.platform == "win32", reason="symbolic links need extra rights on Windows")
def test_links_are_not_followed(tree):
    base, files = tree
    os.symlink(base / "Videos", base / "VideosAgain")                # would count 6.5 MB twice
    os.symlink(base / "setup.exe", base / "setup-link.exe")
    root = scan.walk(str(base))
    assert root.size == sum(files.values()) and "VideosAgain" not in {c.name for c in root.children}


def test_walk_can_be_cancelled(tree):
    base, _ = tree
    with pytest.raises(scan.Cancelled):
        scan.walk(str(base), cancelled=lambda: True)


def test_scan_walks_folders(tree):
    base, files = tree
    root, how = scan.scan(str(base))
    assert how == "walk" and root.size == sum(files.values())


# ---------------------------------------------------------------- the MFT
def test_mft_of_a_real_ntfs_volume(ntfs_image):
    img, files = ntfs_image
    root = mft.read(str(img), "T:\\")
    got = files_of(root)
    for rel, size in files.items():
        assert got.get(rel) == size, rel                             # every file, its name and its exact size
    assert find(root, "Videos/shoot").size == 5_000_000
    assert find(root, "Docs/deep/a/b/c/d/leaf.bin").path() == "T:\\Docs\\deep\\a\\b\\c\\d\\leaf.bin"   # drive paths: backslashes
    assert "$MFT" in {c.name for c in root.children}                 # NTFS's own files take space too
    ours = {k for k in got if not k.startswith("$")}
    assert ours == set(files)                                        # nothing else, no 8.3 short names twice


def test_mft_reports_progress_and_cancels(ntfs_image):
    img, _ = ntfs_image
    seen = []
    mft.read(str(img), "T:\\", progress=seen.append, every=0)
    assert seen and "records" in seen[-1].current
    with pytest.raises(scan.Cancelled):
        mft.read(str(img), "T:\\", cancelled=lambda: True)


def test_mft_refuses_what_isnt_ntfs(tmp_path):
    f = tmp_path / "x.img"
    f.write_bytes(b"\0" * 4096)
    with pytest.raises(mft.NotNTFS):
        mft.read(str(f), "X:\\")


def test_run_lists():
    # 0x21: 1-byte length, 2-byte offset. Runs at cluster 0x1234 (16 long), then 0x10 further on (8 long).
    data = bytes([0x21, 0x10, 0x34, 0x12, 0x11, 0x08, 0x10, 0x00])
    assert mft.runs(data, 0) == [(0x1234, 16), (0x1244, 8)]
    # a negative offset goes back; a run with no offset is sparse (nothing on disk) and left out
    data = bytes([0x11, 0x04, 0xF0, 0x01, 0x05, 0x00])
    assert mft.runs(data, 0) == [(-16, 4)]


@pytest.mark.skipif(sys.platform != "win32" or not scan.is_admin(), reason="Windows with administrator rights (CI)")
@pytest.mark.timeout(900)                      # a whole system drive, read in Python
def test_mft_of_a_real_windows_drive(tmp_path):
    """CI: the runner's own NTFS drive read through its MFT agrees with a walk of a folder made on it."""
    drive = os.path.splitdrive(str(tmp_path))[0]
    base = tmp_path / "pr7du-mft-test"
    from conftest import make_tree
    base.mkdir()
    files = make_tree(base)
    assert scan.file_system(drive + "\\") == "NTFS"
    root, how = scan.scan(drive + "\\")
    assert how == "mft"
    rel = os.path.relpath(base, drive + "\\").replace("\\", "/")
    node = find(root, rel)
    assert files_of(node) == files and node.size == sum(files.values())
