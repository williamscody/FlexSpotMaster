# FlexSpotMaster

**Current release: 1.1.0-beta.1**

FlexSpotMaster is a Windows companion utility for Flex Radio operators. It connects
directly to the FlexRadio TCP API and monitors your panadapter spots in real time.
It offers custom spot text and background colors based upon configurable spot aging.  Depending on your DX Cluster source app, this can provide finer control over your spots.

Often, DX Clusters can report the same spot at slightly different frequencies, which can clutter up your panadapter.  FlexSpotMaster listens to your filter bandwidth, and any spot appearing inside that passband is considered a duplicate, and automatically removed.  This provides a simple, dynamic method to reduce panadapter spot clutter - especially handy during busy CW contests.  This automatic feature is defeatble, and can be set to a fixed "duplicate spot threshold" in Hz.

Based upon my FlexSpotBrige for macOS, FlexSpotMaster for Windows focuses on panadapter spot management: auto duplicate removal, age-based coloring, and smart threshold control.

---

## Features

- Connects to FlexRadio TCP API (port 4992)
- Monitors all panadapter spots (`sub spot all`)
- Detects VFO frequency changes and matches against active spots
- **Duplicate spot removal** — removes older spots within a configurable Hz window when a new spot arrives at the same frequency
- **Optional Auto-Dupe Threshold** — automatically keeps the duplicate window in sync with the current Flex slice filter bandwidth, so the threshold is always exactly right for your current mode and filter setting
- **Age-based spot coloring** — recolors spots on the panadapter based on three configurable age thresholds
- **Background color support** — optionally also colorize the spot background on the panadapter
- **Auto-clear old spots** — automatically removes spots older than a configurable number of minutes
- Clear All Spots function
- Live status bar showing Auto-Dupe state, current filter bandwidth, and active duplicate threshold
- Preferences GUI with real-time color pickers and live spinbox preview

---

## Requirements

- Windows 10 or Windows 11
- Python 3.9 or later (or the standalone `.exe` built with PyInstaller)
- A FlexRadio SDR on the same network
- Windows SmartSDR (for radio operation; this tool connects to the radio API directly)
- A DX Cluster source (typically a logger application)

---

## Quick Start

1. Clone or download the repository.
2. Edit the `FLEX_IP` value near the top of `FlexSpotMaster.py` to match your radio's IP address.
3. Run:

```
python FlexSpotMaster.py
```

4. Open **FlexSpotMaster → Preferences** (or press `Ctrl+,`) to configure all settings.

Settings are saved automatically to `%APPDATA%\FlexSpotMaster\FlexSpotMaster.json`.

---

## Settings

| Setting | Description |
|---|---|
| FLEX_IP | IP address of your FlexRadio |
| FLEX_PORT | TCP port (default 4992) |
| Keep current mode | Do not change slice mode on spot match |
| Remove older spots at same frequency | Enable duplicate spot removal |
| Duplicate threshold | Hz window used for duplicate detection |
| **Enable Auto-Dupe Threshold** | Mirror the current Flex filter bandwidth as the duplicate threshold |
| Auto-clear spots older than | Automatically remove spots past this age |
| Update spot text color | Recolor spot text based on age |
| Update spot background color | Also recolor spot background based on age |
| Verbose debug logging | Print detailed API traffic to the log window |

### Auto-Dupe Threshold

When this setting is on, FlexSpotMaster reads the current slice filter bandwidth from
the Flex API and uses it as the duplicate spot threshold. This means:

- On a 300 Hz CW filter, spots within 300 Hz are considered duplicates
- On a 2.4 kHz SSB filter, spots within 2400 Hz are considered duplicates
- The threshold updates in real time as you change filters

The spinbox in Preferences is disabled while Auto-Dupe is enabled and shows the live value.

### Spot Age Colors

Spots are recolored every 10 seconds based on three configurable buckets:

- **Now** (0 to red threshold): newest spots
- **Red** (red threshold to yellow threshold): moderately aged spots
- **Yellow** (yellow threshold and older): old spots

Text color and background color are each independently configurable. Background can be
set to "None" to leave it at the FlexRadio default.

---

## Building a Standalone Windows Executable

You can build a Windows `.exe` with either `py2exe` or `PyInstaller`.

### Option A: py2exe

1. Install build dependencies:

```
pip install py2exe Pillow
```

2. Create a file named `setup.py` in the project root:

```python
from distutils.core import setup
import py2exe

setup(
	windows=[{"script": "FlexSpotMaster.py"}],
	options={
		"py2exe": {
			"bundle_files": 1,
			"compressed": True,
			"optimize": 2,
		}
	},
	zipfile=None,
)
```

3. Build:

```
python setup.py py2exe
```

The executable will be created in the `dist/` folder.

Note: If `py2exe` does not install cleanly for your Python version, use Option B (`PyInstaller`) below.

### Option B: PyInstaller

```
pip install pyinstaller
pyinstaller --onefile --windowed FlexSpotMaster.py
```

The executable will be in the `dist/` folder.

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+,` | Open Preferences |
| `Ctrl+L` | Clear all spots |

---

## Versioning

| Version | Notes |
|---|---|
| 1.1.0-beta.1 | Initial release; based on FlexSpotBridge 1.1.0-beta.1 feature set |

---

## License

MIT License — see [LICENSE](LICENSE).
