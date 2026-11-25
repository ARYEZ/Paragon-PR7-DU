"""PR7-DU's window, WizTree's layout: the drive and SCAN on top; the folder tree (or the biggest files) beside the
file types; the treemap below; the pointed-at file in the status line.

Scans run on a worker thread (`scan.scan`) and report through queued signals; tests set `sync = True` to run them
inline and `answers` for every question. Everything chosen in one view is shown in the others: a row selects its
block on the map, a block opens the tree down to it."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QModelIndex, QObject, QRectF, QStorageInfo, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QKeySequence, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter, QStackedWidget,
                               QStyledItemDelegate, QTableView, QTreeView, QVBoxLayout, QWidget)

from . import __version__, family, kinds, scan, settings, theme, widgets
from .mapview import MapView
from .models import FRACTION, NODE, FilesModel, TreeModel, TypesModel, human, when
from .scan import Node


def stylesheet() -> str:
    return theme.stylesheet() + f"""
QPushButton[kind="primary"] {{ background: {theme.qss_gradient()}; color: #FFFFFF; border: none; font-weight: 600;
    padding: 7px 22px; }}
QPushButton[kind="primary"]:disabled {{ background: {theme.WIDGET}; color: {theme.TEXT_DIM}; }}
QPushButton[kind="tab"] {{ background: transparent; border: none; border-bottom: 2px solid transparent;
    padding: 6px 12px; color: {theme.TEXT_DIM}; font-weight: 600; }}
QPushButton[kind="tab"][on="true"] {{ color: {theme.TEXT}; border-bottom: 2px solid {theme.ACCENT}; }}
QTreeView, QTableView {{ alternate-background-color: {theme.ALT_ROW}; }}
QTreeView::item:selected, QTreeView::branch:selected, QTableView::item:selected {{
    background: {theme.ACCENT_DIM}; color: #FFFFFF; }}
QTreeView::item {{ padding: 2px 0; }}
"""


class BarDelegate(QStyledItemDelegate):
    """% of parent: the family gradient bar and the number (white on the selection band)."""

    def paint(self, p: QPainter, option, index):
        super().paint(p, option, index)
        frac = index.data(FRACTION) or 0.0
        r = QRectF(option.rect).adjusted(6, option.rect.height() / 2 - 4, -52, -(option.rect.height() / 2 - 4))
        p.save()
        p.fillRect(r, QColor(theme.WIDGET))
        if frac > 0:
            p.fillRect(QRectF(r.x(), r.y(), max(1.0, r.width() * frac), r.height()),
                       theme.family_gradient(r.left(), 0, r.right(), 0))
        f = QFont("Inter"); f.setPixelSize(11); p.setFont(f)
        selected = bool(option.state & option.state.State_Selected) if hasattr(option.state, "State_Selected") else \
            bool(int(option.state) & 0x00008000)
        p.setPen(QColor("#FFFFFF" if selected else theme.TEXT))
        p.drawText(QRectF(r.right() + 4, option.rect.y(), 46, option.rect.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"{frac * 100:.1f} %")
        p.restore()


class _Bridge(QObject):
    progress = Signal(object)
    done = Signal(object, str, str)      # tree, how, error


def drives() -> list[tuple[str, str]]:
    """(root path, label) for every ready drive: "C:  WINDOWS  ·  476.9 GB  ·  164.2 GB FREE"."""
    out = []
    for v in QStorageInfo.mountedVolumes():
        if not v.isValid() or not v.isReady() or v.bytesTotal() <= 0:
            continue
        root = v.rootPath()
        if sys.platform == "win32":
            root = root.replace("/", "\\")
            name = (v.displayName() if v.displayName() != v.rootPath() else "").upper()
            label = f"{root[:2]}  {name}  ·  {human(v.bytesTotal())}  ·  {human(v.bytesAvailable())} FREE"
        else:
            if root.startswith(("/proc", "/sys", "/dev", "/run")):
                continue
            label = f"{root}  ·  {human(v.bytesTotal())}  ·  {human(v.bytesAvailable())} FREE"
        out.append((root, label.replace("    ", "  ")))
    return out


def send_to_trash(path: str) -> None:
    """The Recycle Bin (QFile.moveToTrash), or the folder PR7DU_TRASH names (tests: never the real bin)."""
    target = os.environ.get("PR7DU_TRASH")
    if target:
        os.makedirs(target, exist_ok=True)
        shutil.move(path, os.path.join(target, os.path.basename(path)))
        return
    from PySide6.QtCore import QFile
    if not QFile.moveToTrash(path):
        raise OSError(f"{os.path.basename(path)} couldn’t be moved to the Recycle Bin.")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.answers: dict = {}
        self.sync = False
        self.root: Node | None = None
        self.how = ""
        self.scanning = False
        self.scanned_path = ""
        self._cancel = threading.Event()
        self._started = 0.0
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._progress)
        self.bridge.done.connect(self._done)
        self.setWindowTitle("Paragon PR7-DU")
        self.resize(1280, 860)
        self._build()
        self._actions()
        self.restyle()
        self.fill_drives()

    # ---------------------------------------------------------------- the window
    def _build(self):
        body = QWidget(); self.setCentralWidget(body)
        v = QVBoxLayout(body); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        self.header = widgets.Header("DISK USAGE")
        v.addWidget(self.header)
        bar = QHBoxLayout(); bar.setContentsMargins(16, 10, 16, 10); bar.setSpacing(10)
        self.drive = QComboBox(); self.drive.setMinimumWidth(330)
        bar.addWidget(self.drive)
        self.scan_button = QPushButton("SCAN"); self.scan_button.setProperty("kind", "primary")
        self.scan_button.clicked.connect(self._scan_or_cancel)
        bar.addWidget(self.scan_button)
        self.folder_button = QPushButton("FOLDER...")
        self.folder_button.clicked.connect(self.choose_folder)
        bar.addWidget(self.folder_button)
        self.admin_button = QPushButton("FASTER AS ADMINISTRATOR")
        self.admin_button.setToolTip("Read the drive's own index (its Master File Table) the way WizTree does: "
                                     "seconds instead of minutes. Windows asks for permission once.")
        self.admin_button.clicked.connect(self.restart_as_admin)
        self.admin_button.hide()
        bar.addWidget(self.admin_button)
        bar.addSpacing(10)
        self.summary = QLabel("Choose a drive and press SCAN.")
        self.summary.setProperty("role", "dim")
        bar.addWidget(self.summary, 1)
        self.tabs = {}
        for key, text in (("tree", "TREE"), ("files", "FILES")):
            b = QPushButton(text); b.setProperty("kind", "tab")
            b.clicked.connect(lambda _=False, k=key: self.show_view(k))
            bar.addWidget(b)
            self.tabs[key] = b
        self.menu_key = widgets.SmallKey("more", "PR7-DU")
        self.menu_key.clicked.connect(self.main_menu)
        bar.addWidget(self.menu_key)
        v.addLayout(bar)

        self.tree_model = TreeModel()
        self.tree = QTreeView()
        self.tree.setModel(self.tree_model)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setItemDelegateForColumn(1, BarDelegate(self.tree))
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(lambda pos: self._view_menu(self.tree, pos))
        self.tree.selectionModel().currentChanged.connect(lambda cur, _: self._chosen(cur))
        self.tree.doubleClicked.connect(lambda idx: self.open_node(idx.data(NODE)) if idx.data(NODE) and
                                        not idx.data(NODE).is_dir else None)
        h = self.tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, w in ((1, 140), (2, 84), (3, 84), (4, 70), (5, 70), (6, 70), (7, 124)):
            h.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            self.tree.setColumnWidth(col, w)
        self.tree.hideColumn(3)                     # ALLOCATED: on in the menu (WizTree hides it too)

        self.files_model = FilesModel()
        self.files = QTableView()
        self.files.setModel(self.files_model)
        self._table(self.files, {0: 230, 2: 84, 3: 84, 4: 90, 5: 124}, stretch=1)
        self.files.hideColumn(3)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(lambda pos: self._view_menu(self.files, pos))
        self.files.selectionModel().currentChanged.connect(lambda cur, _: self._chosen(cur))
        self.files.doubleClicked.connect(lambda idx: self.open_node(idx.data(NODE)))

        self.types_model = TypesModel()
        self.types = QTableView()
        self.types.setModel(self.types_model)
        self._table(self.types, {1: 64, 2: 84, 3: 64}, stretch=0)
        self.types.selectionModel().currentChanged.connect(lambda cur, _: self._type_chosen(cur))

        self.views = QStackedWidget()
        self.views.addWidget(self.tree)
        self.views.addWidget(self.files)
        top = QSplitter(Qt.Orientation.Horizontal)
        top.addWidget(self.views)
        top.addWidget(self.types)
        top.setSizes([940, 340])
        self.map = MapView()
        self.map.hovered.connect(self._hovered)
        self.map.clicked.connect(self.reveal)
        self.map.menu.connect(lambda node, gpos: self.node_menu(node, gpos.toPoint()))
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(top)
        split.addWidget(self.map)
        split.setSizes([420, 360])
        v.addWidget(split, 1)
        status = QHBoxLayout(); status.setContentsMargins(16, 6, 16, 8)
        self.where = QLabel("")
        self.what = QLabel(""); self.what.setProperty("role", "dim")
        status.addWidget(self.where, 1)
        status.addWidget(self.what)
        v.addLayout(status)
        self.show_view("tree")

    def _table(self, t: QTableView, widths: dict, stretch: int):
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        t.setAlternatingRowColors(True)
        t.setShowGrid(False)
        t.verticalHeader().hide()
        t.verticalHeader().setDefaultSectionSize(26)
        h = t.horizontalHeader()
        h.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
        for col, w in widths.items():
            h.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            t.setColumnWidth(col, w)

    def _actions(self):
        for keys, fn in ((QKeySequence.StandardKey.Refresh, self.rescan), ("F5", self.rescan),
                         (QKeySequence.StandardKey.Copy, self.copy_path), (QKeySequence.StandardKey.Delete,
                                                                            self.delete_selected)):
            a = QAction(self)
            a.setShortcut(QKeySequence(keys))
            a.triggered.connect(fn)
            self.addAction(a)

    def restyle(self):
        app = QApplication.instance()
        app.setPalette(theme.palette())
        self.setStyleSheet(stylesheet())
        self.header.update()
        if self.map.root is not None:
            self.map.refresh()

    def show_view(self, key: str):
        self.views.setCurrentWidget(self.tree if key == "tree" else self.files)
        for k, b in self.tabs.items():
            b.setProperty("on", k == key)
            b.style().unpolish(b); b.style().polish(b)

    def fill_drives(self):
        self.drive.clear()
        for root, label in drives():
            self.drive.addItem(label, root)
        last = settings.get("drive", "")
        i = self.drive.findData(last) if last else -1
        if i < 0 and sys.platform == "win32":
            i = self.drive.findData(os.environ.get("SystemDrive", "C:") + "\\")
        if i >= 0:
            self.drive.setCurrentIndex(i)
        self.drive.currentIndexChanged.connect(lambda _: self._drive_changed())
        self._drive_changed()

    def _drive_changed(self):
        root = self.drive.currentData() or ""
        fast_possible = (sys.platform == "win32" and bool(root) and scan.file_system(root) == "NTFS"
                         and not scan.is_admin())
        self.admin_button.setVisible(fast_possible)

    # ---------------------------------------------------------------- scanning
    def _scan_or_cancel(self):
        if self.scanning:
            self._cancel.set()
            self.summary.setText("Stopping...")
        else:
            root = self.drive.currentData()
            if root:
                settings.set("drive", root)
                self.start_scan(root)

    def choose_folder(self):
        path = self._ask("folder", None)
        if path:
            self.start_scan(path)

    def rescan(self):
        if self.scanned_path and not self.scanning:
            self.start_scan(self.scanned_path)

    def start_scan(self, path: str):
        if self.scanning:
            return
        self.scanning = True
        self.scanned_path = path
        self._cancel.clear()
        self._started = time.monotonic()
        self.scan_button.setText("CANCEL")
        self.folder_button.setEnabled(False)
        self.summary.setText(f"Scanning {path} ...")
        work = lambda: scan.scan(path, self.bridge.progress.emit, self._cancel.is_set)   # noqa: E731

        def run():
            try:
                tree, how = work()
                self.bridge.done.emit(tree, how, "")
            except scan.Cancelled:
                self.bridge.done.emit(None, "", "cancelled")
            except Exception as e:  # noqa: BLE001 - shown in the summary line
                self.bridge.done.emit(None, "", str(e))
        if self.sync:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

    def _progress(self, p):
        if self.scanning:
            self.summary.setText(f"{p.files:,} files  ·  {human(p.bytes)}  ·  {p.current}")

    def _done(self, tree, how, error):
        self.scanning = False
        self.scan_button.setText("SCAN")
        self.folder_button.setEnabled(True)
        if error:
            self.summary.setText("Scan cancelled." if error == "cancelled" else f"The scan stopped: {error}")
            return
        self.how = how
        self.set_tree(tree)
        took = time.monotonic() - self._started
        self.summary.setText(f"{human(tree.size)} in {tree.files:,} files  ·  scanned in {took:.1f} s"
                             + ("  (the drive's own index)" if how == "mft" else ""))

    def set_tree(self, tree: Node):
        self.root = tree
        self.tree_model.set_root(tree)
        self.files_model.set_root(tree)
        self.types_model.set_root(tree)
        self.map.set_root(tree)
        top = self.tree_model.index(0, 0)
        self.tree.expand(top)
        self.tree.setCurrentIndex(top)

    # ---------------------------------------------------------------- choosing, in any view
    def _chosen(self, index: QModelIndex):
        node = index.data(NODE) if index.isValid() else None
        self.map.highlight(node)
        self._describe(node)

    def _type_chosen(self, index: QModelIndex):
        """A type: its files on the map are outlined in turn by the status line's count."""
        if not index.isValid():
            return
        ext = index.data(TypesModel.EXT)
        self.where.setText(f".{ext}" if ext else "(no extension)")
        self.what.setText(index.siblingAtColumn(2).data() + "  ·  " + index.siblingAtColumn(3).data() + " files")

    def reveal(self, node: Node):
        """A block clicked on the map: open the tree down to it and select it (or its row in FILES)."""
        if self.views.currentWidget() is self.files and node in self.files_model.rows:
            self.files.setCurrentIndex(self.files_model.index(self.files_model.rows.index(node), 0))
            return
        chain = []
        n = node
        while n is not None:
            chain.append(n)
            n = n.parent
        for a in reversed(chain[1:]):
            self.tree.expand(self.tree_model.index_of(a))
        idx = self.tree_model.index_of(node)
        self.tree.setCurrentIndex(idx)
        self.tree.scrollTo(idx)

    def _hovered(self, node: Node | None):
        self._describe(node if node is not None else self.selected())

    def _describe(self, node: Node | None):
        if node is None:
            self.where.setText(""); self.what.setText("")
            return
        self.where.setText(node.path())
        kind = "FOLDER" if node.is_dir else kinds.kind_of(node.name).upper()
        extra = f"  ·  {node.files:,} files" if node.is_dir else ""
        self.what.setText(f"{human(node.size)}  ·  {kind}{extra}  ·  modified {when(node.mtime)}")

    def selected(self) -> Node | None:
        view = self.views.currentWidget()
        idx = view.currentIndex()
        return idx.data(NODE) if idx.isValid() else None

    # ---------------------------------------------------------------- what can be done with a file
    def _view_menu(self, view, pos):
        idx = view.indexAt(pos)
        if idx.isValid():
            view.setCurrentIndex(idx)
            self.node_menu(idx.data(NODE), view.viewport().mapToGlobal(pos))

    def node_menu(self, node: Node | None, gpos=None) -> QMenu | None:
        if node is None:
            return None
        m = QMenu(self)
        m.addAction("Open", lambda: self.open_node(node))
        m.addAction("Show in folder", lambda: self.show_in_folder(node))
        m.addAction("Copy path", lambda: self.copy_path(node))
        m.addSeparator()
        d = m.addAction("Delete (to the Recycle Bin)...", lambda: self.delete(node))
        d.setEnabled(node.parent is not None and not self.scanning)
        self.last_menu = m
        if "menu" in self.answers or gpos is None:
            return m
        m.exec(gpos)
        return m

    def open_node(self, node: Node | None):
        if node is None:
            return
        launch = self.answers.get("open")
        if launch:
            launch(node.path())
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(node.path()))

    def show_in_folder(self, node: Node):
        """The file's folder: PR7-E when it's the family's folder app, else Explorer with the file selected."""
        folder = node.path() if node.is_dir else os.path.dirname(node.path())
        launch = self.answers.get("launch", family.launch)
        if family.pr7e_for_folders() or "launch" in self.answers:
            if launch("PR7-E", [folder]):
                return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", node.path()])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def copy_path(self, node: Node | None = None):
        node = node if isinstance(node, Node) else self.selected()
        if node is not None:
            QApplication.clipboard().setText(node.path())

    def delete_selected(self):
        node = self.selected()
        if node is not None:
            self.delete(node)

    def delete(self, node: Node) -> bool:
        """Into the Recycle Bin, then out of the tree, the lists and the map; every folder above gets smaller."""
        if node.parent is None or self.scanning:
            return False
        what = f"the folder {node.name} and everything in it" if node.is_dir else node.name
        if not self._ask("delete", f"Move {what} ({human(node.size)}) to the Recycle Bin?"):
            return False
        try:
            send_to_trash(node.path())
        except OSError as e:
            self._say("warning", str(e))
            return False
        parent = node.parent
        row = parent.children.index(node)
        pidx = self.tree_model.index_of(parent)
        self.tree_model.beginRemoveRows(pidx, row, row)
        parent.children.pop(row)
        self.tree_model.removed(node, parent, row)
        self.tree_model.endRemoveRows()
        a = parent
        while a is not None:
            a.size -= node.size
            a.alloc -= node.alloc
            a.files -= node.files
            a.folders -= node.folders + (1 if node.is_dir else 0)
            i = self.tree_model.index_of(a)
            self.tree_model.dataChanged.emit(i, i.siblingAtColumn(self.tree_model.columnCount() - 1))
            a = a.parent
        stack = [node]
        while stack:
            n = stack.pop()
            if n.children is None:
                self.files_model.forget(n)
            else:
                stack.extend(n.children)
        node.parent = None
        self.types_model.set_root(self.root)
        self.map.refresh()
        self.summary.setText(f"{human(self.root.size)} in {self.root.files:,} files  ·  "
                             f"{human(node.size)} moved to the Recycle Bin")
        return True

    # ---------------------------------------------------------------- faster with the drive's own index
    def restart_as_admin(self):
        """Start PR7-DU again with administrator rights (Windows asks), scanning this drive; this one closes."""
        root = self.drive.currentData()
        if sys.platform != "win32" or not root:
            return
        import ctypes
        exe = sys.executable
        args = f'--elevated --scan "{root}"'
        if not getattr(sys, "frozen", False):
            args = f'-m pr7du {args}'
        if ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1) > 32:
            self.close()

    # ---------------------------------------------------------------- the PR7-DU menu
    def main_menu(self):
        m = QMenu(self)
        for name in ("obsidian", "aurora"):
            a = m.addAction(name.upper())
            a.setCheckable(True); a.setChecked(theme.FINISH == name)
            a.triggered.connect(lambda _=False, n=name: self.set_finish(n))
        m.addSeparator()
        alloc = m.addAction("Show allocated size")
        alloc.setCheckable(True); alloc.setChecked(not self.tree.isColumnHidden(3))
        alloc.toggled.connect(self.show_allocated)
        m.addSeparator()
        m.addAction("Check for updates...").triggered.connect(self.check_updates)
        m.addAction("About PR7-DU").triggered.connect(
            lambda: self._say("info", f"Paragon PR7-DU {__version__}\nShows what fills a disk, the way WizTree does."))
        self.last_menu = m
        if "menu" in self.answers:
            return m
        m.exec(self.menu_key.mapToGlobal(self.menu_key.rect().bottomLeft()))
        return m

    def show_allocated(self, on: bool):
        self.tree.setColumnHidden(3, not on)
        self.files.setColumnHidden(3, not on)

    def set_finish(self, name: str):
        theme.set_finish(name)
        settings.set("finish", name)
        self.restyle()

    def check_updates(self):
        from . import update_ui
        update_ui.check(self, manual=True)

    # ---------------------------------------------------------------- questions
    def _ask(self, kind: str, text):
        if kind in self.answers:
            a = self.answers[kind]
            return a(text) if callable(a) else a
        if kind == "folder":
            return QFileDialog.getExistingDirectory(self, "Scan a folder", self.scanned_path or os.path.expanduser("~"))
        return QMessageBox.question(self, "Paragon PR7-DU", text) == QMessageBox.StandardButton.Yes

    def _say(self, kind: str, text: str):
        if "say" in self.answers:
            self.answers["say"](kind, text)
            return
        (QMessageBox.warning if kind == "warning" else QMessageBox.information)(self, "Paragon PR7-DU", text)

    def closeEvent(self, e):
        self._cancel.set()
        e.accept()
