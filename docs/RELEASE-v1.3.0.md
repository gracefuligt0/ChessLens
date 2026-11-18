# ChessLens v1.3.0

A portable Windows chess-analysis companion with local Stockfish 19, board markers, explanations, sacrifice ideas, simpler-move suggestions and played-move celebrations.

## Download

1. Download **ChessLens-v1.3.0-Windows-x64.zip** from the Assets list below.
2. Right-click it and choose **Extract All**.
3. Open the extracted ChessLens folder and run **ChessLens.exe**. Keep the other files beside it.
4. Connect Chrome, Edge, Brave or Firefox using the included **Browser-Connector/SETUP.html** guide, then refresh Chess.com.

No Python, Stockfish installation, subscription or API key is needed for the Windows ZIP. The build targets Windows 10/11 x64 and is currently unsigned.

## New in this public release

- Browser connectors for Chrome, Microsoft Edge, Brave and Firefox.
- Independent local visual title badges for either player: GM, IM, FM, CM, WGM, WIM, WFM and WCM. Enable them in the desktop app's Options; each player has its own on/off control.
- An original celebration chime and custom WAV import. Personal voice clips are not bundled.
- Licensed piece artwork, corresponding Stockfish source, rebuild scripts and checksums.

The top three ranked suggestions remain visible alongside optional blue sacrifice ideas and purple natural-move markers. Nothing is played automatically. Titles and brilliant labels are local visual/analysis features, not official credentials or grades.

Firefox uses **Load Temporary Add-on** at `about:debugging#/runtime/this-firefox`; this unsigned connector needs loading again after Firefox restarts. Chromium browsers use **Load unpacked** on their extensions page. Browser stores, Safari, mobile devices and native macOS/Linux binaries are outside this release.

## Files

- **Windows-x64.zip** — complete portable app, engine and both connectors; choose this to run ChessLens.
- **Chromium-Connector.zip** — connector alone for Chrome, Edge or Brave.
- **Firefox-Connector.zip** — Firefox connector alone.
- **Source.zip** — application, connectors, licensed artwork and corresponding Stockfish source; choose this to inspect or rebuild.
- **SHA256SUMS.txt** — SHA-256 hashes for the release ZIPs.

Validated with 88 unit/regression checks, packaged startup/recognition/engine checks, and isolated connector tests in all four browsers, including per-player title toggles and native-title restoration.
