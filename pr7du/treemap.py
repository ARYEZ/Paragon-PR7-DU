"""The treemap's layout (no Qt): every file a rectangle whose area is its size, folders nested inside their parent.

Squarified treemaps (Bruls, Huizing & van Wijk, 2000), as WizTree and WinDirStat draw them: items, largest first,
are laid in rows along the shorter side of the space left, and a row grows while that keeps its rectangles closer to
square. Square-ish blocks keep small files visible and easy to point at, where slicing in strips makes slivers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return self.w * self.h

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


def _worst(row: list[float], side: float) -> float:
    """The worst aspect ratio (>= 1) of a row of areas laid along `side`."""
    s = sum(row)
    if s <= 0 or side <= 0:
        return float("inf")
    hi, lo = max(row), min(row)
    return max(side * side * hi / (s * s), (s * s) / (side * side * lo))


def squarify(sizes: list[float], box: Box) -> list[Box]:
    """Rectangles for `sizes` (any order; zeros get empty boxes) filling `box`, in the same order as `sizes`."""
    out: list[Box | None] = [None] * len(sizes)
    order = sorted((i for i, v in enumerate(sizes) if v > 0), key=lambda i: -sizes[i])
    total = sum(sizes[i] for i in order)
    for i, v in enumerate(sizes):
        if v <= 0:
            out[i] = Box(box.x, box.y, 0, 0)
    if total <= 0 or box.area <= 0:
        return [b or Box(box.x, box.y, 0, 0) for b in out]
    scale = box.area / total
    areas = [sizes[i] * scale for i in order]
    x, y, w, h = box.x, box.y, box.w, box.h
    k = 0
    while k < len(order):
        side = min(w, h)
        row = [areas[k]]
        j = k + 1
        while j < len(order) and _worst(row + [areas[j]], side) <= _worst(row, side):
            row.append(areas[j])
            j += 1
        s = sum(row)
        if w >= h:                       # a column at the left, as tall as the space
            cw = s / h if h else 0
            cy = y
            for n, a in enumerate(row):
                ch = a / cw if cw else 0
                out[order[k + n]] = Box(x, cy, cw, ch)
                cy += ch
            x, w = x + cw, w - cw
        else:                            # a row at the top, as wide as the space
            rh = s / w if w else 0
            cx = x
            for n, a in enumerate(row):
                rw = a / rh if rh else 0
                out[order[k + n]] = Box(cx, y, rw, rh)
                cx += rw
            y, h = y + rh, h - rh
        k = j
    return out  # type: ignore[return-value]


@dataclass
class Tile:
    """A file (or, too small to open up, a whole folder) on the map."""
    box: Box
    node: object
    depth: int


def layout(node, box: Box, children=lambda n: n.children, size=lambda n: n.size, inset: float = 1.0,
           min_side: float = 2.0, depth: int = 0) -> list[Tile]:
    """Every file's tile inside `box`. Folders are laid out recursively and lose `inset` on each side, so a thin
    frame shows where each folder ends (WizTree's look); anything smaller than `min_side` stops there as one tile."""
    kids = [c for c in (children(node) or []) if size(c) > 0]
    if not kids or box.w < min_side * 2 or box.h < min_side * 2:
        return [Tile(box, node, depth)]
    inner = Box(box.x + inset, box.y + inset, box.w - 2 * inset, box.h - 2 * inset) if depth else box
    tiles: list[Tile] = []
    for c, b in zip(kids, squarify([size(c) for c in kids], inner)):
        if b.w < min_side or b.h < min_side:
            tiles.append(Tile(b, c, depth + 1))
        elif children(c):
            tiles.extend(layout(c, b, children, size, inset, min_side, depth + 1))
        else:
            tiles.append(Tile(b, c, depth + 1))
    return tiles


def tile_at(tiles: list[Tile], px: float, py: float) -> Tile | None:
    for t in reversed(tiles):
        if t.box.contains(px, py):
            return t
    return None
