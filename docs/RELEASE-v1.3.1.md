# ChessLens v1.3.1 — title positioning

Fixed custom title badges appearing before the avatar or on the wrong header line. Badges now sit immediately before the username text, on the same line, matching Chess.com's normal title placement. Avatars, ratings, flags and material rows retain their layout. Each player's title can still be enabled or disabled independently.

Browser layout checks cover nested name containers, block-style name buttons, zoom, longer titles, board flipping, repeated updates and header rerenders. The fix is included in both browser connectors.

## Update

Download **ChessLens-v1.3.1-Windows-x64.zip**, choose **Extract All**, and run **ChessLens.exe** from the extracted folder. The desktop engine is unchanged; this patch updates the connector and documentation.

If ChessLens is already installed, you can instead download the appropriate connector ZIP and replace the files in your existing unpacked connector folder. Reload ChessLens on your browser's extensions page and refresh Chess.com. Check that the connector shows **1.3.1**.

Chrome, Edge and Brave use the Chromium connector. Firefox uses the Firefox connector through **Load Temporary Add-on**; it needs reloading after Firefox restarts. Full setup instructions are in the README and SETUP.html. Checksums and corresponding source accompany the Windows download.
