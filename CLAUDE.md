# Paragon PR7-DU: notes for Claude

**Paragon PR7-DU** is the owner's personal disk-usage viewer: Python (**PySide6**) that **works the way WizTree
works**, in the Paragon family look (PR7-Z, W, L, F, E, R, P, M, Q, PR7-U `ARYEZ/Paragon-PR7-U`). The repo is
Paragon-PR7-DU (Paragon-PR7-D was already taken). Windows 10/11 x64 is the target; it runs on Linux for tests. The
owner writes Python; explain the why of changes.

## How it's built

- `pr7du/scan.py` (no Qt): `Node` (slots: name, size, alloc, mtime, children None for files, parent, files, folders;
  `path()` joins drive roots with backslashes on any system), `finish` (iterative totals, children largest first),
  `walk` (os.scandir; junctions / symlinks / reparse points not followed; progress, cancel), `scan(path)` -> (tree,
  "mft" | "walk"): MFT when `can_read_mft` (drive root, admin, NTFS), else the walk, also when the MFT read fails.
- `pr7du/mft.py` (no Qt): NTFS read from `\\.\C:` (or an image file in tests): boot sector, the MFT's own run list from
  record 0, records in 4 MB reads, fixups, FILE_NAME (DOS 8.3 names skipped when a long one exists), unnamed DATA
  (real / allocated sizes), STANDARD_INFORMATION mtime; extension records merged into their base; `build` hangs
  orphans and loops on the root. Tests build a real NTFS volume with mkntfs + ntfs-3g (FUSE); CI reads the runner's C:.
- `pr7du/treemap.py` (no Qt): squarified layout (`squarify`, `layout` with folder insets, `tile_at`). `kinds.py`: each
  extension's kind and its family colour. `mapview.py`: the map drawn once into a cached image; `box_of` cached.
- `pr7du/models.py`: plain Python models (never QStandardItemModel): `TreeModel` (rows cached per folder),
  `FilesModel` (5000 biggest), `TypesModel`. `main_window.py`: scans on a thread (`sync = True` in tests), `answers`
  for every question, `delete` (Recycle Bin via QFile.moveToTrash, or PR7DU_TRASH in tests; totals shrink up the
  chain), `restart_as_admin` (ShellExecute "runas" with `--elevated --scan`). `app.py`: one window per user
  (QLocalSocket hand-off, PR7-R's Windows fix), `--selftest FOLDER OUT.json`.
- Installer `installer/pr7du.iss` (per user, AppId {9DFF1917-658D-4BE5-8C19-A88E7150AC24} permanent). CI installs it;
  `tools/verify_install.py installed` scans a known folder and reads C: through its MFT with the installed exe.
- Updates: `pr7du/updates.py` / `update_ui.py` (the family's files, keep them in step; with PR7-U installed, update_ui
  offers it); `family.py`: the family's AppIds (PR7-DU included).

- `pr7du/finish.py` (no Qt): the family's finish (OBSIDIAN / AURORA), one choice for every app: HKCU\Software\Paragon\Family "Finish" (a file elsewhere; PARAGON_FAMILY_FILE in tests, conftest). `finish.start` at start-up, `set_finish` saves it, app.py's 2 s timer `finish.follow`s another app's switch. The same file in every family app: keep them in step.

## The look (family rules)

- Theme is PR7-U's (OBSIDIAN + AURORA via `theme.set_finish`). Colours: the family's only, map colours included
  (`tests/test_scan.py::test_kinds` checks them). Inter; labels UPPER CASE; file names keep their case.
- The PR7-DU mark: PR7 `Logo.cpp` geometry plus D and U (`widgets.D_OUTER/D_COUNTER/U_SHAPE`); icon "7DU" by
  `tools/make_icon.py`, wizard art by `tools/make_installer_art.py`. Check visuals with
  `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT`.

## Rules

- Behaviour questions: do what WizTree does (views, colours by type, the map, right-click actions).
- Tests: `python -m pytest` (offscreen) on real folders in temp dirs and real NTFS images. Never the real settings
  (conftest) or Recycle Bin (PR7DU_TRASH).
- Releases: bump `__version__` in `pr7du/__init__.py` and add a `## x.y.z` section to CHANGELOG.md, then push: CI
  publishes that version by itself once every check has passed. Run workflow / `v*` tags still work.
