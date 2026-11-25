"""Start PR7-DU.

    PR7-DU.exe [folder or drive]      the window (scanning that folder or drive straight away)
    PR7-DU.exe --scan PATH            the same; started again, the running PR7-DU scans it instead
    PR7-DU.exe --version
    PR7-DU.exe --selftest FOLDER OUT.json   scan FOLDER offscreen with the real window and write what it found
                                            (CI checks the installed program with it)
    --elevated                        (internal) the copy started with administrator rights: its own window
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys

TIMEOUT_MS = 1500


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    return "Paragon-PR7-DU-" + hashlib.sha1(user.encode()).hexdigest()[:12]


def hand_over(path: str) -> bool:
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(server_name())
    if not s.waitForConnected(TIMEOUT_MS):
        return False
    s.write(json.dumps({"scan": path}).encode() + b"\n")
    s.flush()
    s.waitForBytesWritten(TIMEOUT_MS)
    if not s.waitForDisconnected(TIMEOUT_MS):
        s.disconnectFromServer()
    return True


def listen(window):
    """Later starts hand over to this window (PR7-R's hand-off, with its Windows fix)."""
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    QLocalServer.removeServer(server_name())
    if not server.listen(server_name()):
        return None

    def connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        buf = bytearray()
        done = []

        def read():
            buf.extend(bytes(sock.readAll()))
            if buf.endswith(b"\n") and not done:
                done.append(True)
                try:
                    msg = json.loads(buf.decode())
                except ValueError:
                    return
                window.showNormal(); window.raise_(); window.activateWindow()
                if msg.get("scan"):
                    window.start_scan(msg["scan"])
                sock.disconnectFromServer()
        sock.readyRead.connect(read)
        sock.disconnected.connect(read)
        if sock.bytesAvailable():
            read()
    server.newConnection.connect(connection)
    window.instance_server = server
    return server


def selftest(folder: str, out: str) -> int:
    """The real window, offscreen, scanning `folder`: what the tree, the file list, the types and the map hold."""
    import tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
    result = {}
    try:
        from . import __version__, theme
        from .main_window import MainWindow
        app = QApplication.instance() or QApplication(sys.argv[:1])
        theme.load_fonts()
        from PySide6.QtGui import QFontDatabase
        w = MainWindow()
        w.sync = True
        w.resize(1200, 800)
        w.show()
        app.processEvents()
        w.start_scan(folder)
        app.processEvents()
        root = w.root
        result = {"version": __version__, "how": w.how, "size": root.size, "files": root.files,
                  "folders": root.folders, "children": {c.name: c.size for c in root.children},
                  "biggest": [n.name for n in w.files_model.rows[:5]],
                  "types": [r[0] for r in w.types_model.rows[:5]], "tiles": len(w.map.tiles),
                  "fonts": "Inter" in QFontDatabase.families()}
        w.close()
    except Exception as e:  # noqa: BLE001 - reported in the output
        result = {"error": f"{type(e).__name__}: {e}"}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return 0 if "size" in result else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--version"]:
        from . import __version__
        print(__version__)
        return 0
    if argv[:1] == ["--selftest"] and len(argv) == 3:
        return selftest(argv[1], argv[2])
    elevated = "--elevated" in argv
    argv = [a for a in argv if a != "--elevated"]
    path = ""
    if argv[:1] == ["--scan"] and len(argv) > 1:
        path = argv[1]
    elif argv and not argv[0].startswith("-"):
        path = argv[0]
    if path.endswith('"'):                 # Explorer's "C:\" arrives as C:"
        path = path[:-1] + "\\"
    from PySide6.QtWidgets import QApplication

    from . import settings, theme
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Paragon")
    app.setApplicationName("PR7-DU")
    if not elevated and hand_over(path):
        return 0
    theme.set_finish(settings.get("finish", "obsidian"))
    theme.load_fonts()
    from PySide6.QtGui import QIcon
    icon = os.path.join(os.path.dirname(__file__), "icons", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    from .main_window import MainWindow
    win = MainWindow()
    listen(win)
    win.show()
    if path:
        win.start_scan(os.path.abspath(path))
    from . import update_ui
    update_ui.start(win)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
