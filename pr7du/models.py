"""The window's three lists as plain Python models (never QStandardItemModel: its item ownership crashed PySide in
PR7-Z): the folder tree, the biggest files, and the file types. Sizes in decimal units, as WizTree and Explorer's
own Properties show them."""

from __future__ import annotations

import time

from PySide6.QtCore import QAbstractItemModel, QAbstractTableModel, QModelIndex, Qt

from . import kinds
from .scan import Node

NODE = Qt.ItemDataRole.UserRole + 1
FRACTION = Qt.ItemDataRole.UserRole + 2     # % of parent, 0..1 (the bar)
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def human(n: float) -> str:
    for unit, k in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= k:
            return f"{n / k:,.1f} {unit}"
    return f"{int(n):,} B"


def when(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t > 0 else ""


class TreeModel(QAbstractItemModel):
    COLUMNS = ["NAME", "% OF PARENT", "SIZE", "ALLOCATED", "ITEMS", "FILES", "FOLDERS", "MODIFIED"]

    def __init__(self, root: Node | None = None):
        super().__init__()
        self.root: Node | None = None
        self._rows: dict[int, dict[int, int]] = {}      # id(folder) -> {id(child): row}
        self.set_root(root)

    def set_root(self, root: Node | None):
        self.beginResetModel()
        self.root = root
        self._rows.clear()
        self.endResetModel()

    def node(self, index: QModelIndex) -> Node | None:
        return index.internalPointer() if index.isValid() else None

    def _row_of(self, node: Node) -> int:
        parent = node.parent
        rows = self._rows.get(id(parent))
        if rows is None:
            rows = self._rows[id(parent)] = {id(c): i for i, c in enumerate(parent.children)}
        return rows[id(node)]

    def index_of(self, node: Node) -> QModelIndex:
        if node is None or self.root is None:
            return QModelIndex()
        if node is self.root:
            return self.createIndex(0, 0, node)
        return self.createIndex(self._row_of(node), 0, node)

    # ---- QAbstractItemModel
    def index(self, row, column, parent=QModelIndex()):
        if self.root is None:
            return QModelIndex()
        if not parent.isValid():
            return self.createIndex(row, column, self.root) if row == 0 else QModelIndex()
        p = parent.internalPointer()
        if p.children is None or not 0 <= row < len(p.children):
            return QModelIndex()
        return self.createIndex(row, column, p.children[row])

    def parent(self, index=QModelIndex()):
        if not index.isValid():
            return QModelIndex()
        n = index.internalPointer()
        if n is self.root or n.parent is None:
            return QModelIndex()
        return self.index_of(n.parent)

    def rowCount(self, parent=QModelIndex()):
        if self.root is None:
            return 0
        if not parent.isValid():
            return 1
        if parent.column() > 0:
            return 0
        n = parent.internalPointer()
        return len(n.children) if n.children else 0

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def hasChildren(self, parent=QModelIndex()):
        if not parent.isValid():
            return self.root is not None
        n = parent.internalPointer()
        return bool(n.children)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        n: Node = index.internalPointer()
        c = index.column()
        if role == NODE:
            return n
        if role == FRACTION:
            if n.parent is None or not n.parent.size:
                return 1.0 if n.parent is None else 0.0
            return n.size / n.parent.size
        if role == Qt.ItemDataRole.DisplayRole:
            if c == 0:
                return n.name + ("\\" if n.is_dir and n.parent is not None else "")
            if c == 2:
                return human(n.size)
            if c == 3:
                return human(n.alloc)
            if n.is_dir and c in (4, 5, 6):
                return f"{(n.items, n.files, n.folders)[c - 4]:,}"
            if c == 7:
                return when(n.mtime)
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole and c >= 2:
            return RIGHT
        if role == Qt.ItemDataRole.ToolTipRole and c == 0:
            return n.path()
        return None

    def removed(self, node: Node, parent: Node, row: int):
        """After `node` left `parent` (deleted): tell the views, forget cached rows."""
        self._rows.pop(id(parent), None)


class FilesModel(QAbstractTableModel):
    """The biggest files anywhere in the scan, largest first (WizTree's File View)."""
    COLUMNS = ["FILE", "FOLDER", "SIZE", "ALLOCATED", "TYPE", "MODIFIED"]
    LIMIT = 5000

    def __init__(self):
        super().__init__()
        self.rows: list[Node] = []
        self.total = 0

    def set_root(self, root: Node | None):
        self.beginResetModel()
        files: list[Node] = []
        stack = [root] if root else []
        while stack:
            n = stack.pop()
            if n.children is None:
                files.append(n)
            else:
                stack.extend(n.children)
        self.total = len(files)
        files.sort(key=lambda n: -n.size)
        self.rows = files[: self.LIMIT]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        n = self.rows[index.row()]
        c = index.column()
        if role == NODE:
            return n
        if role == Qt.ItemDataRole.DisplayRole:
            return (n.name, n.parent.path() if n.parent else "", human(n.size), human(n.alloc),
                    kinds.kind_of(n.name).upper(), when(n.mtime))[c]
        if role == Qt.ItemDataRole.TextAlignmentRole and c in (2, 3):
            return RIGHT
        if role == Qt.ItemDataRole.ToolTipRole:
            return n.path()
        return None

    def forget(self, node: Node):
        if node in self.rows:
            r = self.rows.index(node)
            self.beginRemoveRows(QModelIndex(), r, r)
            del self.rows[r]
            self.endRemoveRows()


class TypesModel(QAbstractTableModel):
    """Every extension's share: % of the scan, size, number of files."""
    COLUMNS = ["TYPE", "%", "SIZE", "FILES"]
    EXT = Qt.ItemDataRole.UserRole + 3

    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, int, int]] = []
        self.total = 0

    def set_root(self, root: Node | None):
        self.beginResetModel()
        by: dict[str, list[int]] = {}
        stack = [root] if root else []
        while stack:
            n = stack.pop()
            if n.children is None:
                e = kinds.ext_of(n.name)
                v = by.get(e)
                if v is None:
                    by[e] = [n.size, 1]
                else:
                    v[0] += n.size
                    v[1] += 1
            else:
                stack.extend(n.children)
        self.rows = sorted(((e, s, k) for e, (s, k) in by.items()), key=lambda r: -r[1])
        self.total = root.size if root else 0
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e, s, k = self.rows[index.row()]
        c = index.column()
        if role == self.EXT:
            return e
        if role == Qt.ItemDataRole.DisplayRole:
            return (f".{e}" if e else "(no extension)", f"{s / self.total * 100:.1f} %" if self.total else "",
                    human(s), f"{k:,}")[c]
        if role == Qt.ItemDataRole.DecorationRole and c == 0:
            from PySide6.QtGui import QColor
            return QColor(kinds.KINDS[kinds.BY_EXT.get(e, "other")][0])
        if role == Qt.ItemDataRole.ToolTipRole and c == 0:
            return kinds.BY_EXT.get(e, "other").upper()
        if role == Qt.ItemDataRole.TextAlignmentRole and c:
            return RIGHT
        return None
