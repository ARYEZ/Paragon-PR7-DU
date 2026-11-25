"""What's on a disk, as a tree (no Qt).

`Node` is a file or a folder; a folder's size, allocated size, file and folder counts are its contents' totals
(`finish`). Two ways to fill the tree:

- `walk(path)`: os.scandir folder by folder, any file system, no special rights. Junctions and symbolic links are
  not followed (they point at folders counted elsewhere; following them would count the same space twice, and
  some loop), as WizTree does.
- `mft.read(volume)`: NTFS's Master File Table read straight from the drive, WizTree's way: one sequential read
  instead of a question per folder. Needs administrator rights; `scan` falls back to `walk` without them.

`scan(path)` picks: a whole NTFS drive with administrator rights -> the MFT, anything else -> the walk."""

from __future__ import annotations

import os
import stat
import sys
import time
from dataclasses import dataclass


class Node:
    __slots__ = ("name", "size", "alloc", "mtime", "children", "parent", "files", "folders")

    def __init__(self, name: str, size: int = 0, alloc: int = 0, mtime: float = 0.0, is_dir: bool = False,
                 parent: "Node | None" = None):
        self.name = name
        self.size = size
        self.alloc = alloc
        self.mtime = mtime
        self.children: list[Node] | None = [] if is_dir else None
        self.parent = parent
        self.files = 0 if is_dir else 1
        self.folders = 0

    @property
    def is_dir(self) -> bool:
        return self.children is not None

    @property
    def items(self) -> int:
        return self.files + self.folders

    def path(self) -> str:
        parts = []
        n: Node | None = self
        while n is not None:
            parts.append(n.name)
            n = n.parent
        parts.reverse()
        import ntpath
        join = ntpath.join if ntpath.splitdrive(parts[0])[0] else os.path.join     # "C:\\" -> backslashes anywhere
        out = parts[0]
        for p in parts[1:]:
            out = join(out, p)
        return out

    def add(self, child: "Node") -> "Node":
        child.parent = self
        self.children.append(child)
        return child

    def __repr__(self) -> str:
        return f"Node({self.name!r}, {self.size}{', dir' if self.is_dir else ''})"


def finish(root: Node) -> Node:
    """Totals for every folder (size, allocated, files, folders, newest change) and children largest first.
    Iterative: a deep tree would overflow Python's recursion limit."""
    order: list[Node] = []
    stack = [root]
    while stack:
        n = stack.pop()
        order.append(n)
        if n.children:
            stack.extend(n.children)
    for n in reversed(order):                     # children before their parent
        if n.children is None:
            continue
        size = alloc = files = folders = 0
        mtime = n.mtime
        for c in n.children:
            size += c.size
            alloc += c.alloc
            files += c.files
            folders += c.folders + (1 if c.children is not None else 0)
            if c.mtime > mtime:
                mtime = c.mtime
        n.size, n.alloc, n.files, n.folders, n.mtime = size, alloc, files, folders, mtime
        n.children.sort(key=lambda c: -c.size)
    return root


@dataclass
class Progress:
    files: int = 0
    bytes: int = 0
    current: str = ""
    errors: int = 0


class Cancelled(Exception):
    pass


def _cluster(path: str) -> int:
    """The drive's cluster size: what a file really takes is its size rounded up to whole clusters."""
    if sys.platform == "win32":
        import ctypes
        root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
        spc, bps, free, total = (ctypes.c_ulong() for _ in range(4))
        if ctypes.windll.kernel32.GetDiskFreeSpaceW(root, ctypes.byref(spc), ctypes.byref(bps), ctypes.byref(free),
                                                    ctypes.byref(total)):
            return spc.value * bps.value or 4096
        return 4096
    try:
        return os.statvfs(path).f_frsize or 4096
    except (OSError, AttributeError):
        return 4096


def _skip_link(entry: os.DirEntry) -> bool:
    """Symbolic links and Windows junctions / other reparse points (not followed)."""
    try:
        if entry.is_symlink():
            return True
        if sys.platform == "win32":
            st = entry.stat(follow_symlinks=False)
            return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True
    return False


def walk(path: str, progress=None, cancelled=lambda: False, every: float = 0.1) -> Node:
    """The folder tree under `path` by os.scandir. progress(Progress) is called at most every `every` seconds."""
    path = os.path.abspath(path)
    cluster = _cluster(path)
    root = Node(path, is_dir=True)
    try:
        root.mtime = os.stat(path).st_mtime
    except OSError:
        pass
    p = Progress()
    last = 0.0
    stack = [(root, path)]
    while stack:
        if cancelled():
            raise Cancelled()
        node, folder = stack.pop()
        try:
            it = os.scandir(folder)
        except OSError:
            p.errors += 1
            continue
        with it:
            for e in it:
                try:
                    if _skip_link(e):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        child = node.add(Node(e.name, mtime=st.st_mtime, is_dir=True))
                        stack.append((child, e.path))
                    else:
                        st = e.stat(follow_symlinks=False)
                        size = st.st_size
                        blocks = getattr(st, "st_blocks", None)
                        alloc = blocks * 512 if blocks is not None else -(-size // cluster) * cluster
                        node.add(Node(e.name, size, alloc, st.st_mtime))
                        p.files += 1
                        p.bytes += size
                except OSError:
                    p.errors += 1
        if progress is not None:
            now = time.monotonic()
            if now - last >= every:
                last = now
                p.current = folder
                progress(p)
    root.name = path
    finish(root)
    if progress is not None:                      # the last word: totals and how many folders couldn't be read
        p.current = ""
        progress(p)
    return root


def is_drive_root(path: str) -> bool:
    p = os.path.abspath(path)
    drive, rest = os.path.splitdrive(p)
    return bool(drive) and rest in ("\\", "/", "")


def file_system(path: str) -> str:
    """ "NTFS", "FAT32", "exFAT", ... for the drive holding `path` ("" when unknown)."""
    if sys.platform != "win32":
        return ""
    import ctypes
    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    buf = ctypes.create_unicode_buffer(64)
    if ctypes.windll.kernel32.GetVolumeInformationW(root, None, 0, None, None, None, buf, 64):
        return buf.value
    return ""


def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def can_read_mft(path: str) -> bool:
    return is_drive_root(path) and is_admin() and file_system(path) == "NTFS"


def scan(path: str, progress=None, cancelled=lambda: False) -> tuple[Node, str]:
    """(tree, how): "mft" when the drive's own index could be read, else "walk"."""
    if can_read_mft(path):
        from . import mft
        drive = os.path.splitdrive(os.path.abspath(path))[0]
        try:
            return mft.read("\\\\.\\" + drive, drive + "\\", progress, cancelled), "mft"
        except Cancelled:
            raise
        except Exception:  # noqa: BLE001 - anything odd about the volume: the ordinary walk still works
            pass
    return walk(path, progress, cancelled), "walk"
