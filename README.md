# OverCut
A lightweight Windows desktop app that summons a floating shortcut reference overlay from any application via a global hotkey. No window switching, no alt-tabbing — just press and glance.
Show Image Show Image Show Image

What it does
Press your configured hotkey from anywhere — inside a game, a browser, a terminal — and a semi-transparent overlay slides in from the bottom-right corner showing all your shortcuts. Press Esc or the hotkey again to dismiss it.
Manage your shortcuts by category through the manager window. Everything persists to a local JSON file next to the executable.

Features

Global hotkey — summons the overlay from any focused application
Overlay — frameless, semi-transparent, always on top, bottom-right corner
Slide-in / fade-out animation — smooth entrance and exit
Live search — filters across key, action, and category in real time
Keyboard navigation — ↑ ↓ to move through results, Esc to clear search or close
Amber highlight — matched rows highlight on search
Category system — group shortcuts by app or context
Manager window — add, edit, delete shortcuts and categories
Configurable hotkey — change and apply without restarting
System tray — minimises to tray, double-click to reopen
Persistent data — saves to overcut_data.json next to the exe
Animated top bar — slow glowing blue sweep because why not


Stack
LanguagePython 3.13UIPyQt6Global hotkeykeyboard libPackagingPyInstallerFontsInter, JetBrains Mono, Roboto Condensed, Zalando Sans Expanded

Getting started
Requirements
pip install PyQt6 keyboard

Must be run as Administrator on Windows — the keyboard library requires elevated privileges for global hotkey capture. The app will auto-prompt for UAC elevation on launch.

Run from source
python overcut.py
Build exe
python -m PyInstaller --onefile --windowed --name "OverCut" --collect-all PyQt6 --add-data "fonts;fonts" --icon="overcut.ico" overcut.py
Output lands in dist/OverCut.exe. Fonts are bundled into the executable — no separate folder needed.

Fonts
Drop TTF/OTF files into a fonts/ folder next to the script or exe. The loader registers them automatically at startup and prints the resolved family names to console.
Bundled fonts used in this project:

Inter — primary UI font
JetBrains Mono — key badges, hotkey field
Roboto Condensed — section labels
Zalando Sans Expanded — display title

All available from Google Fonts / JetBrains.

Default shortcuts
Ships pre-loaded with Jupyter Notebook shortcuts as a reference set. Replace or extend via the manager window.

Project structure
OverCut/
├── overcut.py          # Full application source
├── overcut.ico         # Tray + exe icon
├── fonts/              # Bundled TTF fonts
└── overcut_data.json   # Auto-generated on first run (user data)

.gitignore
build/
dist/
__pycache__/
*.spec
*.pyc
overcut_data.json

Known limitations

Windows only — uses ctypes for UAC elevation and keyboard lib is Windows-focused
Requires admin rights for global hotkey capture
No import/export for shortcut data yet
