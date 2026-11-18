# Third-party notices

- **Stockfish 19**, Stockfish developers, GPL-3.0. The official Windows universal executable is included in binary releases. Its license, authors, full corresponding source, wiki and build scripts are in `src/assets/engine/stockfish` in the source release/repository. [Upstream source](https://github.com/official-stockfish/Stockfish/tree/sf_19). The fetch script pins official archive and executable hashes.
- **python-chess / chess 1.11.2**, Niklas Fiekas and contributors, GPL-3.0-or-later. License in `licenses/python-chess-GPL.txt`. [Source](https://github.com/niklasf/python-chess/tree/v1.11.2).
- **PySide6 / Qt 6.12.0**, The Qt Company and contributors, LGPL-3.0 and applicable third-party terms. Libraries are dynamically linked and kept replaceable under `_internal`. License notices are in `licenses/dependencies`. [PySide source](https://code.qt.io/pyside/pyside-setup.git/?h=6.12.0), [Qt source](https://code.qt.io/qt/qt5.git/?h=6.12.0), [Qt build instructions](https://doc.qt.io/qt-6/build-sources.html). The application's source/build scripts are provided and modifications may be rebuilt and debugged.
- **OpenCV 5.0.0.93**, Apache-2.0 with component notices in `licenses/dependencies/OpenCV`. [OpenCV source](https://github.com/opencv/opencv), [Python packaging](https://github.com/opencv/opencv-python).
- **NumPy 2.5.4**, BSD-3-Clause and bundled third-party terms. See `licenses/dependencies/numpy-2.5.4.dist-info/licenses`. [Source](https://github.com/numpy/numpy).
- **cburnett pieces**, Colin M. Burnett, and **merida pieces**, Armando Hernandez Marroquin, GPL-2.0-or-later as distributed by Lichess. SVG originals are under `src/assets/pieces`. See `licenses/Lichess-COPYING.md` and the [upstream copying notice](https://github.com/lichess-org/lila/blob/master/COPYING.md). Synthetic test boards/screenshots render this licensed artwork.
- **Original ChessLens celebration chime**, CC0 1.0 Universal; see `src/assets/sounds/LICENSE.txt`.
- **Python 3.12**, Python Software Foundation, PSF License; runtime notice in `licenses/dependencies/Python-LICENSE.txt`. [Source](https://www.python.org/downloads/source/).
- **PyInstaller 6.22.3**, GPL with bootloader exception. [Source](https://github.com/pyinstaller/pyinstaller).

The public package does not include Chess.com's Neo images, the personal-use Alpha piece set, personal screenshots, or third-party Witty Alien voice clips. Users can load their own WAV locally. Custom audio is not uploaded or included in release archives.

ChessLens application code is GPL-3.0-or-later; components retain the terms above. Binary releases are accompanied by a source ZIP and source links in `SOURCE.txt`.
