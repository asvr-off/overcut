# OverCut

A lightweight Windows desktop app that summons a floating shortcut reference overlay from any application via a global hotkey — so you never forget your stack of shortcuts. No window switching, no alt-tabbing. Just press and glance.

---

## What It Does

Press your configured hotkey from anywhere — inside a game, a browser, a terminal, or heavy-shortcut apps like Blender, Photoshop, or DaVinci Resolve — and a semi-transparent overlay slides in from the bottom-right corner showing all your shortcuts. Press `Esc` or the hotkey again to dismiss it.

Manage your shortcuts by category through the manager window. Everything persists to a local JSON file next to the executable. The program relies on this file to restore settings, so keep it alongside `OverCut.exe`.

---

## Features

- **Global hotkey** — summon the overlay from any focused application
- **Overlay** — frameless, semi-transparent, always on top, bottom-right corner
- **Slide-in / fade-out animation** — smooth entrance and exit
- **Live search** — filters across key, action, and category in real time
- **Keyboard navigation** — `↑` `↓` to move through results, `Esc` to clear search or close
- **Category system** — group shortcuts by app or context
- **Manager window** — add, edit, and delete shortcuts and categories
- **Configurable hotkey** — change and apply without restarting
- **System tray** — minimizes to tray, double-click to reopen
- **Persistent data** — saves to `overcut_data.json` next to the exe

---

## Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.13 |
| UI | PyQt6 |
| Global hotkey | `keyboard` |
| Packaging | PyInstaller |
| Fonts | Inter, JetBrains Mono, Roboto Condensed, Zalando Sans Expanded (Google Fonts) |

---

## Getting Started

### Requirements

**Python build users:**

1. Install Python 3.13.
2. Install dependencies:

   ```bash
   pip install PyQt6 keyboard
   ```

> **Must be run as Administrator on Windows** — the `keyboard` library requires elevated privileges for global hotkey capture. The app auto-prompts for UAC elevation on launch.

### Fonts

Drop TTF/OTF files into a `fonts/` folder next to the script or exe. The loader registers them automatically at startup and prints the resolved family names to the console.

Bundled fonts used in this project:

- **Inter** — primary UI font
- **JetBrains Mono** — key badges, hotkey field
- **Roboto Condensed** — section labels
- **Zalando Sans Expanded** — display title

All are available from [Google Fonts](https://fonts.google.com/) and [JetBrains](https://www.jetbrains.com/lp/mono/).

---

## Running from Source

```bash
python overcut.py
```

---

## Building the Executable

Build with Python 3.13:

```bash
python313 -m PyInstaller --onefile --windowed --name "OverCut" --collect-all PyQt6 --add-data "fonts;fonts" --add-data "overcut.ico;." --add-data "CHANGELOG.md;." --icon="overcut.ico" overcut.py
```

Output lands in `dist/OverCut.exe`. Fonts, the icon, and the changelog are bundled into the executable — no separate folder needed.

---

## Default Shortcuts

Ships pre-loaded with Jupyter Notebook shortcuts as a reference set. Replace or extend them via the manager window.

---

## Known Limitations

- **Windows only** — uses `ctypes` for UAC elevation, and the `keyboard` library is Windows-focused
- **Requires admin rights** for global hotkey capture
- **No import/export** for shortcut data yet

---

*This README and parts of the code structure were partially AI-generated.*
