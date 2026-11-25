"""The treemap: every file a block sized by its size, coloured by its kind, in WizTree's cushion shading.

The layout (`treemap.layout`) is worked out once per scan and size and drawn into a cached image, so pointing and
repainting the highlight cost nothing. Pointing shows the file (`hovered`), a click selects it (`clicked`), a right
click asks for its menu (`menu`); `highlight(node)` outlines a file or a whole folder chosen elsewhere."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import kinds, theme, treemap
from .scan import Node


class MapView(QWidget):
    hovered = Signal(object)        # Node or None
    clicked = Signal(object)
    menu = Signal(object, QPointF)  # node, global position

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root: Node | None = None
        self.tiles: list[treemap.Tile] = []
        self.image: QImage | None = None
        self.selected: Node | None = None
        self.hover: Node | None = None
        self._boxes: dict[int, QRectF | None] = {}     # id(node) -> its outline, worked out once per layout
        self.setMouseTracking(True)
        self.setMinimumHeight(160)

    def set_root(self, root: Node | None):
        self.root = root
        self.selected = self.hover = None
        self._relayout()

    def refresh(self):
        """After the tree changed (a deletion): lay out again."""
        self._relayout()

    def highlight(self, node: Node | None):
        self.selected = node
        self.update()

    def _relayout(self):
        self.tiles = []
        self.image = None
        self._boxes = {}
        if self.root is not None and self.width() > 4 and self.height() > 4:
            self.tiles = treemap.layout(self.root, treemap.Box(0, 0, self.width(), self.height()), inset=1.5)
        self.update()

    def resizeEvent(self, e):
        self._relayout()

    def _paint_tiles(self) -> QImage:
        dpr = self.devicePixelRatioF()
        img = QImage(int(self.width() * dpr), int(self.height() * dpr), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(QColor(theme.BACKGROUND))
        p = QPainter(img)
        edge = QPen(QColor(0, 0, 0, 90), 1)
        for t in self.tiles:
            b = t.box
            r = QRectF(b.x, b.y, b.w, b.h)
            c = QColor(kinds.FOLDER if t.node.children is not None else kinds.colour_of(t.node.name))
            if b.w > 3 and b.h > 3:
                g = QLinearGradient(r.topLeft(), r.bottomRight())   # the cushion: lit top-left, shaded bottom-right
                g.setColorAt(0, c.lighter(135))
                g.setColorAt(1, c.darker(150))
                p.fillRect(r, g)
                p.setPen(edge)
                p.drawRect(r.adjusted(0, 0, -1, -1))
            else:
                p.fillRect(r, c)
        p.end()
        return img

    def paintEvent(self, _):
        p = QPainter(self)
        if not self.tiles:
            p.fillRect(self.rect(), QColor(theme.BACKGROUND))
            return
        if self.image is None:
            self.image = self._paint_tiles()
        p.drawImage(0, 0, self.image)
        if self.selected is not None:
            box = self.box_of(self.selected)
            if box is not None:
                p.setPen(QPen(QColor("#FFFFFF"), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(box.adjusted(1, 1, -1, -1))
        if self.hover is not None and self.hover is not self.selected:
            box = self.box_of(self.hover)
            if box is not None:
                p.setPen(QPen(QColor(255, 255, 255, 150), 1))
                p.drawRect(box.adjusted(0.5, 0.5, -0.5, -0.5))

    def box_of(self, node: Node) -> QRectF | None:
        """Where a file or folder is on the map: a file's own block, a folder's blocks' bounds."""
        key = id(node)
        if key not in self._boxes:
            self._boxes[key] = self._find_box(node)
        return self._boxes[key]

    def _find_box(self, node: Node) -> QRectF | None:
        xs, ys, xe, ye = [], [], [], []
        for t in self.tiles:
            n = t.node
            while n is not None and n is not node:
                n = n.parent
            if n is node:
                b = t.box
                xs.append(b.x); ys.append(b.y); xe.append(b.x + b.w); ye.append(b.y + b.h)
        if not xs:
            return None
        return QRectF(min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys))

    def node_at(self, pos: QPointF) -> Node | None:
        t = treemap.tile_at(self.tiles, pos.x(), pos.y())
        return t.node if t else None

    def mouseMoveEvent(self, e):
        n = self.node_at(e.position())
        if n is not self.hover:
            self.hover = n
            self.hovered.emit(n)
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.hovered.emit(None)
        self.update()

    def mousePressEvent(self, e):
        n = self.node_at(e.position())
        if n is None:
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(n)
        elif e.button() == Qt.MouseButton.RightButton:
            self.clicked.emit(n)
            self.menu.emit(n, e.globalPosition())
