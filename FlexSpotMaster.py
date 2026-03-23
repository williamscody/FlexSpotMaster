"""
FlexRadio Spot Master for Windows
----------------------------------

This script connects to a FlexRadio TCP control port (4992).

It listens for spots on the Flex panadapter and focuses on spot housekeeping:
duplicate removal, age-based coloring, and optional auto-clear.

Note: Windows SmartSDR already forwards spot/callsign information to
Windows logger applications directly, so no additional logger integration
is needed here.

Tested environment:
Flex 8400
SmartSDR for Windows
Python 3.9+
"""

import socket
import time
import re
import threading
import tkinter as tk
from tkinter import colorchooser
import sys
import json
import os
import webbrowser

APP_NAME = "FlexSpotMaster"
APP_VERSION = "1.1.0"
APP_PRERELEASE = "beta.1"


def app_version_label():
    return f"{APP_VERSION}-{APP_PRERELEASE}"


CURRENT_FILTER_BANDWIDTH_HZ = None

# ------------------------------------------------
# USER SETTINGS
# ------------------------------------------------

# Flex radio IP
FLEX_IP = "192.168.1.100"

# Flex API port
FLEX_PORT = 4992

# If True, remove older Flex spots that share the same exact frequency.
REMOVE_DUPLICATE_SPOTS = True

# Any new spot within this many Hz of an older spot is treated as a duplicate.
DUPLICATE_SPOT_THRESHOLD_HZ = 25

# If True, show high-volume debug logging in the UI log window.
VERBOSE_LOGGING = False

# If True, automatically remove spots older than AUTO_CLEAR_SPOTS_AGE_MINUTES.
AUTO_CLEAR_SPOTS_ENABLED = False

# Age in minutes beyond which spots are automatically removed (1-99).
AUTO_CLEAR_SPOTS_AGE_MINUTES = 5

# Spot age-based color thresholds and values.
# Ages are interpreted as:
# - 0 to SPOT_AGE_RED_MINUTES-1: SPOT_COLOR_NOW
# - SPOT_AGE_RED_MINUTES to SPOT_AGE_YELLOW_MINUTES-1: SPOT_COLOR_RED
# - SPOT_AGE_YELLOW_MINUTES and older: SPOT_COLOR_YELLOW
DEFAULT_SPOT_COLOR_NOW = "#E141E1"
DEFAULT_SPOT_COLOR_RED = "#FF2D00"
DEFAULT_SPOT_COLOR_YELLOW = "#FFFF00"
DEFAULT_SPOT_BG_COLOR_NOW = "none"
DEFAULT_SPOT_BG_COLOR_RED = "none"
DEFAULT_SPOT_BG_COLOR_YELLOW = "none"

SPOT_AGE_RED_MINUTES = 5
SPOT_AGE_YELLOW_MINUTES = 15
SPOT_COLOR_NOW = DEFAULT_SPOT_COLOR_NOW
SPOT_COLOR_RED = DEFAULT_SPOT_COLOR_RED
SPOT_COLOR_YELLOW = DEFAULT_SPOT_COLOR_YELLOW
SPOT_BG_COLOR_NOW = DEFAULT_SPOT_BG_COLOR_NOW
SPOT_BG_COLOR_RED = DEFAULT_SPOT_BG_COLOR_RED
SPOT_BG_COLOR_YELLOW = DEFAULT_SPOT_BG_COLOR_YELLOW

# If True, set Flex spot text color based on age bucket.
ENABLE_SPOT_TEXT_COLORS = True

# If True, also set Flex spot background_color based on the same age bucket color.
ENABLE_SPOT_BACKGROUND_COLORS = False

# If True, duplicate threshold follows current Flex slice filter bandwidth (Hz).
ENABLE_AUTO_DUPE_THRESHOLD = False

# Track Flex panadapter spots by spot ID -> metadata.
# Example: {"23": {"freq_hz": 7030400, "call": "R4WCQ", "time": 1774154707}}
flex_spots = {}
flex_spots_lock = threading.Lock()
flex_command_seq = 2
flex_command_seq_lock = threading.Lock()


def next_flex_command_seq():
    """Return the next command sequence number for the listener socket."""
    global flex_command_seq
    with flex_command_seq_lock:
        flex_command_seq += 1
        return flex_command_seq


def send_flex_command(command):
    """Send a one-shot command to the Flex API."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((FLEX_IP, FLEX_PORT))
    sock.sendall(f"C1|{command}\n".encode())
    sock.close()


def connect_flex_command_socket():
    """Open a persistent command socket to the Flex API."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((FLEX_IP, FLEX_PORT))
    return sock


def log_debug(*args, **kwargs):
    if VERBOSE_LOGGING:
        print(*args, **kwargs)


def remove_duplicate_flex_spots(freq_hz, keep_spot_id, command_sock=None):
    """Remove older Flex spots within DUPLICATE_SPOT_THRESHOLD_HZ, keeping one ID."""
    with flex_spots_lock:
        duplicate_ids = [
            spot_id
            for spot_id, spot in flex_spots.items()
            if (
                spot_id != keep_spot_id
                and spot.get("freq_hz") is not None
                and abs(int(spot.get("freq_hz")) - int(freq_hz)) <= DUPLICATE_SPOT_THRESHOLD_HZ
            )
        ]

        for spot_id in duplicate_ids:
            flex_spots.pop(spot_id, None)

    for spot_id in duplicate_ids:
        try:
            if command_sock is None:
                send_flex_command(f"spot remove {spot_id}")
            else:
                command_seq = next_flex_command_seq()
                command_sock.sendall(f"C{command_seq}|spot remove {spot_id}\n".encode())
            print(
                f"Removed older Flex spot id={spot_id} within {DUPLICATE_SPOT_THRESHOLD_HZ} Hz of {freq_hz} Hz"
            )
        except Exception as e:
            print(f"Failed to remove Flex spot id={spot_id}: {e}")


# ------------------------------------------------
# SETTINGS PERSISTENCE
# ------------------------------------------------

SETTINGS_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "FlexSpotMaster"
)
SETTINGS_FILE = os.path.join(SETTINGS_DIR, "FlexSpotMaster.json")

def load_settings():
    global FLEX_IP, FLEX_PORT, REMOVE_DUPLICATE_SPOTS, DUPLICATE_SPOT_THRESHOLD_HZ, VERBOSE_LOGGING, AUTO_CLEAR_SPOTS_ENABLED, AUTO_CLEAR_SPOTS_AGE_MINUTES
    global SPOT_AGE_RED_MINUTES, SPOT_AGE_YELLOW_MINUTES, SPOT_COLOR_NOW, SPOT_COLOR_RED, SPOT_COLOR_YELLOW
    global SPOT_BG_COLOR_NOW, SPOT_BG_COLOR_RED, SPOT_BG_COLOR_YELLOW
    global ENABLE_SPOT_TEXT_COLORS, ENABLE_SPOT_BACKGROUND_COLORS, ENABLE_AUTO_DUPE_THRESHOLD
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            FLEX_IP = data.get("FLEX_IP", FLEX_IP)
            FLEX_PORT = int(data.get("FLEX_PORT", FLEX_PORT))
            REMOVE_DUPLICATE_SPOTS = bool(data.get("REMOVE_DUPLICATE_SPOTS", REMOVE_DUPLICATE_SPOTS))
            DUPLICATE_SPOT_THRESHOLD_HZ = int(data.get("DUPLICATE_SPOT_THRESHOLD_HZ", DUPLICATE_SPOT_THRESHOLD_HZ))
            VERBOSE_LOGGING = bool(data.get("VERBOSE_LOGGING", VERBOSE_LOGGING))
            AUTO_CLEAR_SPOTS_ENABLED = bool(data.get("AUTO_CLEAR_SPOTS_ENABLED", AUTO_CLEAR_SPOTS_ENABLED))
            AUTO_CLEAR_SPOTS_AGE_MINUTES = int(data.get("AUTO_CLEAR_SPOTS_AGE_MINUTES", AUTO_CLEAR_SPOTS_AGE_MINUTES))
            SPOT_AGE_RED_MINUTES = int(data.get("SPOT_AGE_RED_MINUTES", SPOT_AGE_RED_MINUTES))
            SPOT_AGE_YELLOW_MINUTES = int(data.get("SPOT_AGE_YELLOW_MINUTES", SPOT_AGE_YELLOW_MINUTES))
            SPOT_COLOR_NOW = str(data.get("SPOT_COLOR_NOW", SPOT_COLOR_NOW))
            SPOT_COLOR_RED = str(data.get("SPOT_COLOR_RED", SPOT_COLOR_RED))
            SPOT_COLOR_YELLOW = str(data.get("SPOT_COLOR_YELLOW", SPOT_COLOR_YELLOW))

            if "SPOT_BG_COLOR_NOW" in data:
                loaded_now_bg = str(data.get("SPOT_BG_COLOR_NOW", SPOT_BG_COLOR_NOW)).strip()
                SPOT_BG_COLOR_NOW = loaded_now_bg if loaded_now_bg else "none"
            else:
                SPOT_BG_COLOR_NOW = DEFAULT_SPOT_BG_COLOR_NOW

            if "SPOT_BG_COLOR_RED" in data:
                loaded_red_bg = str(data.get("SPOT_BG_COLOR_RED", SPOT_BG_COLOR_RED)).strip()
                SPOT_BG_COLOR_RED = loaded_red_bg if loaded_red_bg else "none"
            else:
                SPOT_BG_COLOR_RED = DEFAULT_SPOT_BG_COLOR_RED

            if "SPOT_BG_COLOR_YELLOW" in data:
                loaded_yellow_bg = str(data.get("SPOT_BG_COLOR_YELLOW", SPOT_BG_COLOR_YELLOW)).strip()
                SPOT_BG_COLOR_YELLOW = loaded_yellow_bg if loaded_yellow_bg else "none"
            else:
                SPOT_BG_COLOR_YELLOW = DEFAULT_SPOT_BG_COLOR_YELLOW

            ENABLE_SPOT_TEXT_COLORS = bool(data.get("ENABLE_SPOT_TEXT_COLORS", ENABLE_SPOT_TEXT_COLORS))
            ENABLE_SPOT_BACKGROUND_COLORS = bool(data.get("ENABLE_SPOT_BACKGROUND_COLORS", ENABLE_SPOT_BACKGROUND_COLORS))
            ENABLE_AUTO_DUPE_THRESHOLD = bool(data.get("ENABLE_AUTO_DUPE_THRESHOLD", ENABLE_AUTO_DUPE_THRESHOLD))

            if SPOT_AGE_RED_MINUTES < 1:
                SPOT_AGE_RED_MINUTES = 1
            if SPOT_AGE_YELLOW_MINUTES <= SPOT_AGE_RED_MINUTES:
                SPOT_AGE_YELLOW_MINUTES = SPOT_AGE_RED_MINUTES + 1
            if DUPLICATE_SPOT_THRESHOLD_HZ < 0:
                DUPLICATE_SPOT_THRESHOLD_HZ = 0
        except Exception as e:
            print(f"Failed to load settings: {e}")

def save_settings():
    try:
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        data = {
            "FLEX_IP": FLEX_IP,
            "FLEX_PORT": FLEX_PORT,
            "REMOVE_DUPLICATE_SPOTS": REMOVE_DUPLICATE_SPOTS,
            "DUPLICATE_SPOT_THRESHOLD_HZ": DUPLICATE_SPOT_THRESHOLD_HZ,
            "VERBOSE_LOGGING": VERBOSE_LOGGING,
            "AUTO_CLEAR_SPOTS_ENABLED": AUTO_CLEAR_SPOTS_ENABLED,
            "AUTO_CLEAR_SPOTS_AGE_MINUTES": AUTO_CLEAR_SPOTS_AGE_MINUTES,
            "SPOT_AGE_RED_MINUTES": SPOT_AGE_RED_MINUTES,
            "SPOT_AGE_YELLOW_MINUTES": SPOT_AGE_YELLOW_MINUTES,
            "SPOT_COLOR_NOW": SPOT_COLOR_NOW,
            "SPOT_COLOR_RED": SPOT_COLOR_RED,
            "SPOT_COLOR_YELLOW": SPOT_COLOR_YELLOW,
            "SPOT_BG_COLOR_NOW": SPOT_BG_COLOR_NOW,
            "SPOT_BG_COLOR_RED": SPOT_BG_COLOR_RED,
            "SPOT_BG_COLOR_YELLOW": SPOT_BG_COLOR_YELLOW,
            "ENABLE_SPOT_TEXT_COLORS": ENABLE_SPOT_TEXT_COLORS,
            "ENABLE_SPOT_BACKGROUND_COLORS": ENABLE_SPOT_BACKGROUND_COLORS,
            "ENABLE_AUTO_DUPE_THRESHOLD": ENABLE_AUTO_DUPE_THRESHOLD,
        }
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Failed to save settings: {e}")

load_settings()


def spot_color_for_age(age_seconds):
    """Choose the configured spot color based on spot age."""
    if age_seconds >= SPOT_AGE_YELLOW_MINUTES * 60:
        return SPOT_COLOR_YELLOW
    if age_seconds >= SPOT_AGE_RED_MINUTES * 60:
        return SPOT_COLOR_RED
    return SPOT_COLOR_NOW


def spot_background_color_for_age(age_seconds):
    """Choose the configured spot background color based on spot age."""
    if age_seconds >= SPOT_AGE_YELLOW_MINUTES * 60:
        return SPOT_BG_COLOR_YELLOW
    if age_seconds >= SPOT_AGE_RED_MINUTES * 60:
        return SPOT_BG_COLOR_RED
    return SPOT_BG_COLOR_NOW


def parse_slice_filter_bandwidth_hz(slice_line):
    """Extract a filter bandwidth in Hz from a Flex slice status line."""
    width_keys = ("filter_bw", "filter_width", "filter_bandwidth")
    for key in width_keys:
        width_match = re.search(rf"\b{key}=(-?\d+)\b", slice_line)
        if width_match:
            bandwidth_hz = abs(int(width_match.group(1)))
            if bandwidth_hz > 0:
                return bandwidth_hz

    edge_key_pairs = (
        ("filter_hi", "filter_lo"),
        ("filter_high", "filter_low"),
        ("rx_filter_high", "rx_filter_low"),
    )
    for high_key, low_key in edge_key_pairs:
        high_match = re.search(rf"\b{high_key}=(-?\d+)\b", slice_line)
        low_match = re.search(rf"\b{low_key}=(-?\d+)\b", slice_line)
        if high_match and low_match:
            bandwidth_hz = abs(int(high_match.group(1)) - int(low_match.group(1)))
            if bandwidth_hz > 0:
                return bandwidth_hz

    return None

# ------------------------------------------------
# AUTO-CLEAR OLD SPOTS
# ------------------------------------------------

def clear_old_spots_task():
    """Periodically clear spots older than AUTO_CLEAR_SPOTS_AGE_MINUTES."""
    command_sock = None
    command_seq = 9000

    while True:
        time.sleep(30)  # Check every 30 seconds

        if not AUTO_CLEAR_SPOTS_ENABLED:
            continue

        current_time = int(time.time())
        age_threshold_seconds = AUTO_CLEAR_SPOTS_AGE_MINUTES * 60

        with flex_spots_lock:
            spots_to_remove = [
                spot_id
                for spot_id, spot in flex_spots.items()
                if (current_time - spot.get("time", current_time)) > age_threshold_seconds
            ]

            for spot_id in spots_to_remove:
                flex_spots.pop(spot_id, None)

        if spots_to_remove:
            try:
                for spot_id in spots_to_remove:
                    if command_sock is None:
                        command_sock = connect_flex_command_socket()

                    try:
                        command_seq += 1
                        command_sock.sendall(f"C{command_seq}|spot remove {spot_id}\n".encode())
                    except Exception:
                        try:
                            command_sock.close()
                        except Exception:
                            pass

                        command_sock = connect_flex_command_socket()
                        command_seq += 1
                        command_sock.sendall(f"C{command_seq}|spot remove {spot_id}\n".encode())

                log_debug(f"Auto-cleared {len(spots_to_remove)} old spots")
            except Exception as e:
                log_debug(f"Failed to auto-clear old spots: {e}")
                if command_sock is not None:
                    try:
                        command_sock.close()
                    except Exception:
                        pass
                    command_sock = None


def update_spot_colors_task():
    """Periodically recolor Flex spots based on configurable spot age buckets."""
    command_sock = None
    command_seq = 12000

    while True:
        time.sleep(10)

        if not ENABLE_SPOT_TEXT_COLORS and not ENABLE_SPOT_BACKGROUND_COLORS:
            continue

        now = int(time.time())
        updates = []
        with flex_spots_lock:
            for spot_id, spot in flex_spots.items():
                spot_age_seconds = max(0, now - int(spot.get("time", now)))
                target_text_color = spot_color_for_age(spot_age_seconds)
                target_background_color = spot_background_color_for_age(spot_age_seconds)
                if (
                    spot.get("last_text_color") != target_text_color
                    or spot.get("last_background_color") != target_background_color
                    or spot.get("last_text_enabled") != ENABLE_SPOT_TEXT_COLORS
                    or spot.get("last_background_enabled") != ENABLE_SPOT_BACKGROUND_COLORS
                ):
                    spot["last_text_color"] = target_text_color
                    spot["last_background_color"] = target_background_color
                    spot["last_text_enabled"] = ENABLE_SPOT_TEXT_COLORS
                    spot["last_background_enabled"] = ENABLE_SPOT_BACKGROUND_COLORS
                    updates.append((spot_id, target_text_color, target_background_color))

        for spot_id, target_text_color, target_background_color in updates:
            try:
                if command_sock is None:
                    command_sock = connect_flex_command_socket()

                command_seq += 1
                set_parts = []
                if ENABLE_SPOT_TEXT_COLORS:
                    set_parts.append(f"color={target_text_color}")
                if ENABLE_SPOT_BACKGROUND_COLORS:
                    if str(target_background_color).lower() == "none":
                        set_parts.append("background_color=")
                    else:
                        set_parts.append(f"background_color={target_background_color}")

                if not set_parts:
                    continue

                set_clause = " ".join(set_parts)
                command_sock.sendall(
                    f"C{command_seq}|spot set {spot_id} {set_clause}\n".encode()
                )
                log_debug(f"Updated spot id={spot_id} {set_clause}")
            except Exception as e:
                log_debug(f"Failed to update color for spot id={spot_id}: {e}")
                if command_sock is not None:
                    try:
                        command_sock.close()
                    except Exception:
                        pass
                    command_sock = None


class TextRedirector:
    def __init__(self, widget):
        self.widget = widget

    def write(self, str):
        self.widget.insert(tk.END, str)
        self.widget.see(tk.END)

    def flush(self):
        pass


# ------------------------------------------------
# FLEX RADIO LISTENER
# ------------------------------------------------

def flex_listener():
    global DUPLICATE_SPOT_THRESHOLD_HZ, CURRENT_FILTER_BANDWIDTH_HZ

    print("Connecting to Flex radio...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((FLEX_IP, FLEX_PORT))

    print("Flex connected")

    # subscribe to slice updates
    sock.sendall(b"C1|sub slice all\n")
    sock.sendall(b"C2|sub spot all\n")

    while True:

        data = sock.recv(4096).decode(errors="ignore")

        log_debug("Flex data:", data.strip())

        if not data:
            continue

        for line in data.splitlines():
            log_debug("Flex line:", line)

            spot_match = re.search(
                r"S[^|]+\|spot\s+(\d+)\b",
                line
            )

            removed_match = re.search(r"S[^|]+\|spot\s+removed\s+(\d+)", line)
            if removed_match:
                removed_id = removed_match.group(1)
                with flex_spots_lock:
                    flex_spots.pop(removed_id, None)
                continue

            if spot_match:
                spot_id = spot_match.group(1)

                freq_match = re.search(r"(?:rx_freq|freq)=(\d+(?:\.\d+)?)", line)
                call_match = re.search(r"callsign=([^\s]+)", line)
                timestamp_match = re.search(r"timestamp=(\d+)", line)

                if not freq_match or not call_match:
                    continue

                spot_freq_hz = int(round(float(freq_match.group(1)) * 1e6))
                call = call_match.group(1)
                spot_time = int(timestamp_match.group(1)) if timestamp_match else int(time.time())

                with flex_spots_lock:
                    flex_spots[spot_id] = {
                        "freq_hz": spot_freq_hz,
                        "call": call,
                        "time": spot_time,
                        "last_text_color": None,
                        "last_background_color": None,
                        "last_text_enabled": None,
                        "last_background_enabled": None,
                    }

                if REMOVE_DUPLICATE_SPOTS:
                    remove_duplicate_flex_spots(spot_freq_hz, spot_id, command_sock=sock)

            slice_event_match = re.search(r"S[^|]+\|slice\s+(\d+)\b", line)
            if slice_event_match:
                bandwidth_hz = parse_slice_filter_bandwidth_hz(line)
                if bandwidth_hz:
                    CURRENT_FILTER_BANDWIDTH_HZ = bandwidth_hz

                if ENABLE_AUTO_DUPE_THRESHOLD and bandwidth_hz:
                    if bandwidth_hz != DUPLICATE_SPOT_THRESHOLD_HZ:
                        DUPLICATE_SPOT_THRESHOLD_HZ = bandwidth_hz
                        print(
                            "Auto-Dupe Threshold updated from filter bandwidth: "
                            f"{DUPLICATE_SPOT_THRESHOLD_HZ} Hz"
                        )

                freq_match = re.search(r"\bRF_frequency=(\d+\.\d+)\b", line)
                if not freq_match:
                    continue


class App:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} {app_version_label()}")
        self.root.geometry("600x400")

        self.status_var = tk.StringVar()
        self.status_bar = tk.Label(
            root,
            textvariable=self.status_var,
            anchor="w",
            bg="#ECECEC",
            fg="#202020",
            padx=8,
            pady=4,
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self.text = tk.Text(root, wrap=tk.WORD)
        self.text.pack(expand=True, fill=tk.BOTH)

        def refresh_status_line():
            auto_dupe_state = "ON" if ENABLE_AUTO_DUPE_THRESHOLD else "OFF"
            filter_bw_text = (
                f"{CURRENT_FILTER_BANDWIDTH_HZ} Hz"
                if CURRENT_FILTER_BANDWIDTH_HZ is not None
                else "n/a"
            )
            threshold_text = f"{DUPLICATE_SPOT_THRESHOLD_HZ} Hz"
            self.status_var.set(
                f"Auto-Dupe: {auto_dupe_state} | Filter BW: {filter_bw_text} | Duplicate threshold: {threshold_text}"
            )
            if ENABLE_AUTO_DUPE_THRESHOLD:
                self.status_bar.configure(fg="#0B6E4F")
            else:
                self.status_bar.configure(fg="#5C5C5C")
            self.root.after(250, refresh_status_line)

        refresh_status_line()

        # Redirect stdout
        sys.stdout = TextRedirector(self.text)
        print(f"{APP_NAME} {app_version_label()} starting...")
        print(
            "Auto-Dupe Threshold: "
            + ("enabled" if ENABLE_AUTO_DUPE_THRESHOLD else "disabled")
        )

        # Menu bar
        menubar = tk.Menu(root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(
            label=f"About {APP_NAME}",
            command=self.open_about
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Preferences...",
            accelerator="Ctrl+,",
            command=self.open_settings
        )
        file_menu.add_separator()

        def clear_spots():
            try:
                send_flex_command("spot clear")
                with flex_spots_lock:
                    removed_spots = len(flex_spots)
                    flex_spots.clear()
                print(f"All spots cleared on Flex panadapter. Local spot memory reset ({removed_spots} spots removed).")
            except Exception as e:
                print(f"Failed to clear spots on Flex: {e}")

        file_menu.add_command(
            label="Clear All Spots",
            accelerator="Ctrl+L",
            command=clear_spots
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=root.quit)
        menubar.add_cascade(label=APP_NAME, menu=file_menu)

        root.config(menu=menubar)

        # Keyboard shortcuts
        root.bind_all("<Control-l>", lambda e: clear_spots())
        root.bind_all("<Control-L>", lambda e: clear_spots())

        def open_settings_shortcut(_event=None):
            self.open_settings()
            return "break"

        root.bind_all("<Control-comma>", open_settings_shortcut)

        # Start threads
        flex_thread = threading.Thread(target=flex_listener, daemon=True)
        flex_thread.start()

        clear_old_spots_thread = threading.Thread(target=clear_old_spots_task, daemon=True)
        clear_old_spots_thread.start()

        spot_color_thread = threading.Thread(target=update_spot_colors_task, daemon=True)
        spot_color_thread.start()

    def _load_about_icon_image(self, size=96):
        """Load the app icon for use in the About dialog (PNG or ICO via Pillow)."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base_dir, "FlexSpotMaster.png"),
            os.path.join(base_dir, "FlexSpotMaster.ico"),
            os.path.join(os.getcwd(), "FlexSpotMaster.png"),
            os.path.join(os.getcwd(), "FlexSpotMaster.ico"),
        ]
        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                from PIL import Image, ImageTk
                img = Image.open(path).resize((size, size), Image.LANCZOS)
                return ImageTk.PhotoImage(img)
            except Exception:
                pass
        return None

    def open_about(self):
        about_win = tk.Toplevel(self.root)
        about_win.title(f"About {APP_NAME}")
        dialog_width = 520
        dialog_height = 320
        about_win.geometry(f"{dialog_width}x{dialog_height}")
        about_win.resizable(False, False)
        about_win.transient(self.root)

        # Center over the main app window.
        self.root.update_idletasks()
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_w = self.root.winfo_width()
        root_h = self.root.winfo_height()
        pos_x = root_x + max((root_w - dialog_width) // 2, 0)
        pos_y = root_y + max((root_h - dialog_height) // 2, 0)
        about_win.geometry(f"{dialog_width}x{dialog_height}+{pos_x}+{pos_y}")

        about_win.configure(bg="#FFF4D6")

        outer = tk.Frame(about_win, bg="#FFF4D6", padx=20, pady=20)
        outer.pack(expand=True, fill=tk.BOTH)

        banner = tk.Frame(outer, bg="#0A3D62", padx=16, pady=12)
        banner.pack(fill=tk.X, pady=(0, 14))

        banner_top = tk.Frame(banner, bg="#0A3D62")
        banner_top.pack(fill=tk.X)

        self.about_icon_image = self._load_about_icon_image(size=96)
        if self.about_icon_image is not None:
            tk.Label(
                banner_top,
                image=self.about_icon_image,
                bg="#0A3D62"
            ).pack(side=tk.LEFT, padx=(0, 12))
        else:
            tk.Label(
                banner_top,
                text="FSM",
                font=("Segoe UI", 16, "bold"),
                fg="#F6E58D",
                bg="#0A3D62",
                width=4
            ).pack(side=tk.LEFT, padx=(0, 12))

        title_box = tk.Frame(banner_top, bg="#0A3D62")
        title_box.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(
            title_box,
            text=APP_NAME,
            font=("Segoe UI", 22, "bold"),
            fg="#F6E58D",
            bg="#0A3D62"
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text=f"Version {app_version_label()}",
            font=("Segoe UI", 12, "bold"),
            fg="#DFF9FB",
            bg="#0A3D62"
        ).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(outer, bg="#FFFFFF", padx=16, pady=14, highlightthickness=2, highlightbackground="#F0932B")
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            body,
            text="Created by Bill Cody, K3CDY",
            font=("Segoe UI", 13),
            fg="#130F40",
            bg="#FFFFFF"
        ).pack(anchor="w", pady=(0, 8))

        github_url = "https://github.com/williamscody/FlexSpotMaster"

        tk.Label(
            body,
            text=github_url,
            font=("Consolas", 12),
            fg="#0652DD",
            bg="#FFFFFF",
            cursor="hand2"
        ).pack(anchor="w")

        def open_github(_event=None):
            webbrowser.open(github_url)

        body.bind("<Button-1>", open_github)
        for child in body.winfo_children():
            if isinstance(child, tk.Label) and child.cget("text") == github_url:
                child.bind("<Button-1>", open_github)

        tk.Button(
            outer,
            text="Close",
            command=about_win.destroy,
            bg="#F7F7F7",
            fg="#111111",
            activebackground="#EDEDED",
            activeforeground="#000000",
            font=("Segoe UI", 13, "bold"),
            relief=tk.RAISED,
            bd=1,
            padx=16,
            pady=6
        ).pack(anchor="e", pady=(12, 0))

        about_win.grab_set()
        about_win.focus_set()

    def open_settings(self):
        settings_win = tk.Toplevel(self.root)
        settings_win.title("Preferences")

        # Settings fields
        settings = [
            ("FLEX_IP", "FLEX_IP"),
            ("FLEX_PORT", "FLEX_PORT"),
        ]

        entries = {}
        row = 0
        for label, var_name in settings:
            tk.Label(settings_win, text=f"{label}:").grid(row=row, column=0, sticky="e")
            entry = tk.Entry(settings_win)
            entry.insert(0, str(globals()[var_name]))
            entry.grid(row=row, column=1)
            entries[var_name] = entry
            row += 1

        remove_duplicate_spots_var = tk.BooleanVar(value=REMOVE_DUPLICATE_SPOTS)
        tk.Checkbutton(
            settings_win,
            text="Remove older spots at same frequency",
            variable=remove_duplicate_spots_var
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 8))
        row += 1

        duplicate_threshold_var = tk.IntVar(value=DUPLICATE_SPOT_THRESHOLD_HZ)
        duplicate_threshold_frame = tk.Frame(settings_win, bg="SystemButtonFace")
        duplicate_threshold_frame.grid(row=row, column=0, columnspan=2, sticky="w", padx=28, pady=(0, 8))
        tk.Label(
            duplicate_threshold_frame,
            text="Duplicate threshold:",
            bg="SystemButtonFace"
        ).pack(side=tk.LEFT)
        duplicate_threshold_spinbox = tk.Spinbox(
            duplicate_threshold_frame,
            from_=0,
            to=1000,
            width=5,
            textvariable=duplicate_threshold_var
        )
        duplicate_threshold_spinbox.pack(side=tk.LEFT, padx=(6, 4))
        tk.Label(duplicate_threshold_frame, text="Hz", bg="SystemButtonFace").pack(side=tk.LEFT)
        row += 1

        enable_auto_dupe_threshold_var = tk.BooleanVar(value=ENABLE_AUTO_DUPE_THRESHOLD)
        tk.Checkbutton(
            settings_win,
            text="Enable Auto-Dupe Threshold",
            variable=enable_auto_dupe_threshold_var
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8))
        row += 1

        def update_duplicate_threshold_control_state(*_args):
            if enable_auto_dupe_threshold_var.get():
                duplicate_threshold_spinbox.configure(state="disabled")
                duplicate_threshold_var.set(DUPLICATE_SPOT_THRESHOLD_HZ)
            else:
                duplicate_threshold_spinbox.configure(state="normal")

        enable_auto_dupe_threshold_var.trace_add("write", update_duplicate_threshold_control_state)
        update_duplicate_threshold_control_state()

        def refresh_duplicate_threshold_preview():
            if not settings_win.winfo_exists():
                return
            if enable_auto_dupe_threshold_var.get():
                current_threshold = DUPLICATE_SPOT_THRESHOLD_HZ
                if duplicate_threshold_var.get() != current_threshold:
                    duplicate_threshold_var.set(current_threshold)
            settings_win.after(250, refresh_duplicate_threshold_preview)

        settings_win.after(250, refresh_duplicate_threshold_preview)

        auto_clear_spots_var = tk.BooleanVar(value=AUTO_CLEAR_SPOTS_ENABLED)
        tk.Checkbutton(
            settings_win,
            text="Auto-clear spots older than:",
            variable=auto_clear_spots_var
        ).grid(row=row, column=0, sticky="w", padx=8, pady=(6, 8))

        auto_clear_frame = tk.Frame(settings_win, bg="SystemButtonFace")
        auto_clear_frame.grid(row=row, column=1, sticky="w", padx=0)

        auto_clear_age_var = tk.IntVar(value=AUTO_CLEAR_SPOTS_AGE_MINUTES)
        auto_clear_spinbox = tk.Spinbox(
            auto_clear_frame,
            from_=1,
            to=99,
            width=3,
            textvariable=auto_clear_age_var
        )
        auto_clear_spinbox.pack(side=tk.LEFT, padx=(0, 4))

        tk.Label(auto_clear_frame, text="minutes", bg="SystemButtonFace").pack(side=tk.LEFT)
        row += 1

        verbose_logging_var = tk.BooleanVar(value=VERBOSE_LOGGING)
        tk.Checkbutton(
            settings_win,
            text="Verbose debug logging",
            variable=verbose_logging_var
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 8))
        row += 1

        spot_age_frame = tk.LabelFrame(settings_win, text="Spot Age Colors", padx=10, pady=10)
        spot_age_frame.grid(row=row, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 6))
        settings_win.grid_columnconfigure(1, weight=1)

        now_color_var = tk.StringVar(value=SPOT_COLOR_NOW)
        red_color_var = tk.StringVar(value=SPOT_COLOR_RED)
        yellow_color_var = tk.StringVar(value=SPOT_COLOR_YELLOW)
        now_bg_color_var = tk.StringVar(value=SPOT_BG_COLOR_NOW)
        red_bg_color_var = tk.StringVar(value=SPOT_BG_COLOR_RED)
        yellow_bg_color_var = tk.StringVar(value=SPOT_BG_COLOR_YELLOW)

        red_age_var = tk.IntVar(value=SPOT_AGE_RED_MINUTES)
        yellow_age_var = tk.IntVar(value=SPOT_AGE_YELLOW_MINUTES)

        def refresh_swatch(swatch_canvas, rect_id, color_var):
            color = color_var.get()
            label_id = swatch_canvas._none_label_id
            if str(color).lower() == "none":
                swatch_canvas.itemconfigure(rect_id, fill="#2E2E2E", outline="#9A9A9A")
                swatch_canvas.itemconfigure(label_id, text="NONE", fill="#FFFFFF")
            else:
                swatch_canvas.itemconfigure(rect_id, fill=color, outline=color)
                swatch_canvas.itemconfigure(label_id, text="")

        def choose_color(color_var, refresh_callback):
            current_color = color_var.get()
            initial_color = current_color if str(current_color).startswith("#") else "#000000"
            result = colorchooser.askcolor(color=initial_color, parent=settings_win, title="Choose spot color")
            if result and result[1]:
                color_var.set(result[1])
                refresh_callback()

        def make_swatch(parent, color_var):
            swatch = tk.Canvas(
                parent,
                width=110,
                height=30,
                highlightthickness=1,
                highlightbackground="#B8B8B8",
                bd=0,
                cursor="hand2"
            )
            swatch_rect = swatch.create_rectangle(4, 6, 106, 24)
            swatch._none_label_id = swatch.create_text(55, 15, text="", font=("Segoe UI", 10, "bold"))
            refresh_fn = lambda: refresh_swatch(swatch, swatch_rect, color_var)
            refresh_fn()
            color_var.trace_add("write", lambda *_args: refresh_fn())
            swatch.bind("<Button-1>", lambda _event: choose_color(color_var, refresh_fn))
            return swatch

        tk.Label(spot_age_frame, text="Now").grid(row=0, column=1, padx=(0, 12), pady=(0, 6), sticky="w")
        tk.Label(spot_age_frame, text="Red").grid(row=0, column=2, padx=(0, 12), pady=(0, 6), sticky="w")
        tk.Label(spot_age_frame, text="Yellow").grid(row=0, column=3, padx=(0, 12), pady=(0, 6), sticky="w")

        tk.Label(spot_age_frame, text="Text").grid(row=1, column=0, padx=(0, 12), pady=(0, 6), sticky="w")
        make_swatch(spot_age_frame, now_color_var).grid(row=1, column=1, padx=(0, 12), pady=(0, 6), sticky="w")
        make_swatch(spot_age_frame, red_color_var).grid(row=1, column=2, padx=(0, 12), pady=(0, 6), sticky="w")
        make_swatch(spot_age_frame, yellow_color_var).grid(row=1, column=3, padx=(0, 12), pady=(0, 6), sticky="w")

        tk.Label(spot_age_frame, text="Background").grid(row=2, column=0, padx=(0, 12), pady=(0, 6), sticky="w")
        make_swatch(spot_age_frame, now_bg_color_var).grid(row=2, column=1, padx=(0, 12), pady=(0, 6), sticky="w")
        make_swatch(spot_age_frame, red_bg_color_var).grid(row=2, column=2, padx=(0, 12), pady=(0, 6), sticky="w")
        make_swatch(spot_age_frame, yellow_bg_color_var).grid(row=2, column=3, padx=(0, 12), pady=(0, 6), sticky="w")

        tk.Button(spot_age_frame, text="None", command=lambda: now_bg_color_var.set("none"), padx=8).grid(
            row=3, column=1, padx=(0, 12), pady=(0, 6), sticky="w"
        )
        tk.Button(spot_age_frame, text="None", command=lambda: red_bg_color_var.set("none"), padx=8).grid(
            row=3, column=2, padx=(0, 12), pady=(0, 6), sticky="w"
        )
        tk.Button(spot_age_frame, text="None", command=lambda: yellow_bg_color_var.set("none"), padx=8).grid(
            row=3, column=3, padx=(0, 12), pady=(0, 6), sticky="w"
        )

        tk.Label(spot_age_frame, text="Age").grid(row=4, column=0, padx=(0, 12), pady=(2, 0), sticky="w")
        tk.Label(spot_age_frame, text="Fixed at 0 min").grid(row=4, column=1, padx=(0, 12), pady=(2, 0), sticky="w")
        red_age_spin = tk.Spinbox(spot_age_frame, from_=1, to=240, width=4, textvariable=red_age_var)
        red_age_spin.grid(row=4, column=2, padx=(0, 12), pady=(2, 0), sticky="w")
        yellow_age_spin = tk.Spinbox(spot_age_frame, from_=2, to=240, width=4, textvariable=yellow_age_var)
        yellow_age_spin.grid(row=4, column=3, padx=(0, 12), pady=(2, 0), sticky="w")
        tk.Label(spot_age_frame, text="minutes").grid(row=4, column=4, sticky="w", pady=(2, 0))

        def set_age_defaults():
            red_age_var.set(5)
            yellow_age_var.set(15)
            now_color_var.set(DEFAULT_SPOT_COLOR_NOW)
            red_color_var.set(DEFAULT_SPOT_COLOR_RED)
            yellow_color_var.set(DEFAULT_SPOT_COLOR_YELLOW)
            now_bg_color_var.set(DEFAULT_SPOT_BG_COLOR_NOW)
            red_bg_color_var.set(DEFAULT_SPOT_BG_COLOR_RED)
            yellow_bg_color_var.set(DEFAULT_SPOT_BG_COLOR_YELLOW)

        tk.Button(spot_age_frame, text="Default", command=set_age_defaults).grid(
            row=5, column=0, columnspan=5, pady=(10, 0)
        )

        enable_text_colors_var = tk.BooleanVar(value=ENABLE_SPOT_TEXT_COLORS)
        tk.Checkbutton(
            spot_age_frame,
            text="Update spot text color",
            variable=enable_text_colors_var
        ).grid(row=6, column=0, columnspan=5, sticky="w", pady=(8, 0))

        enable_background_colors_var = tk.BooleanVar(value=ENABLE_SPOT_BACKGROUND_COLORS)
        tk.Checkbutton(
            spot_age_frame,
            text="Update spot background color",
            variable=enable_background_colors_var
        ).grid(row=7, column=0, columnspan=5, sticky="w", pady=(2, 0))

        mode_preview_var = tk.StringVar()

        def update_mode_preview(*_args):
            text_enabled = enable_text_colors_var.get()
            background_enabled = enable_background_colors_var.get()

            if text_enabled and background_enabled:
                mode_preview_var.set("Active mode: text + background")
            elif text_enabled:
                mode_preview_var.set("Active mode: text only")
            elif background_enabled:
                mode_preview_var.set("Active mode: background only")
            else:
                mode_preview_var.set("Active mode: disabled")

        enable_text_colors_var.trace_add("write", update_mode_preview)
        enable_background_colors_var.trace_add("write", update_mode_preview)
        update_mode_preview()

        tk.Label(
            spot_age_frame,
            textvariable=mode_preview_var,
            fg="#FFFFFF"
        ).grid(row=8, column=0, columnspan=5, sticky="w", pady=(8, 0))

        row += 1

        def save():
            global REMOVE_DUPLICATE_SPOTS, DUPLICATE_SPOT_THRESHOLD_HZ, VERBOSE_LOGGING, AUTO_CLEAR_SPOTS_ENABLED, AUTO_CLEAR_SPOTS_AGE_MINUTES
            global SPOT_AGE_RED_MINUTES, SPOT_AGE_YELLOW_MINUTES, SPOT_COLOR_NOW, SPOT_COLOR_RED, SPOT_COLOR_YELLOW
            global SPOT_BG_COLOR_NOW, SPOT_BG_COLOR_RED, SPOT_BG_COLOR_YELLOW
            global ENABLE_SPOT_TEXT_COLORS, ENABLE_SPOT_BACKGROUND_COLORS, ENABLE_AUTO_DUPE_THRESHOLD
            for var_name, entry in entries.items():
                value = entry.get()
                if var_name in ["FLEX_PORT"]:
                    globals()[var_name] = int(value)
                else:
                    globals()[var_name] = value

            try:
                red_minutes = int(red_age_var.get())
                yellow_minutes = int(yellow_age_var.get())
                duplicate_threshold_hz = int(duplicate_threshold_var.get())
            except ValueError:
                print("Spot age and duplicate threshold settings must be whole numbers")
                return

            if red_minutes < 1:
                print("Red spot age must be at least 1 minute")
                return

            if yellow_minutes <= red_minutes:
                print("Yellow spot age must be greater than red spot age")
                return

            if duplicate_threshold_hz < 0:
                print("Duplicate threshold must be 0 Hz or greater")
                return

            REMOVE_DUPLICATE_SPOTS = remove_duplicate_spots_var.get()
            ENABLE_AUTO_DUPE_THRESHOLD = enable_auto_dupe_threshold_var.get()
            if not ENABLE_AUTO_DUPE_THRESHOLD:
                DUPLICATE_SPOT_THRESHOLD_HZ = duplicate_threshold_hz
            AUTO_CLEAR_SPOTS_ENABLED = auto_clear_spots_var.get()
            AUTO_CLEAR_SPOTS_AGE_MINUTES = auto_clear_age_var.get()
            VERBOSE_LOGGING = verbose_logging_var.get()
            SPOT_AGE_RED_MINUTES = red_minutes
            SPOT_AGE_YELLOW_MINUTES = yellow_minutes
            SPOT_COLOR_NOW = now_color_var.get()
            SPOT_COLOR_RED = red_color_var.get()
            SPOT_COLOR_YELLOW = yellow_color_var.get()
            SPOT_BG_COLOR_NOW = now_bg_color_var.get()
            SPOT_BG_COLOR_RED = red_bg_color_var.get()
            SPOT_BG_COLOR_YELLOW = yellow_bg_color_var.get()
            ENABLE_SPOT_TEXT_COLORS = enable_text_colors_var.get()
            ENABLE_SPOT_BACKGROUND_COLORS = enable_background_colors_var.get()

            # Force all tracked spots to be recolored against the new settings.
            with flex_spots_lock:
                for spot in flex_spots.values():
                    spot["last_text_color"] = None
                    spot["last_background_color"] = None
                    spot["last_text_enabled"] = None
                    spot["last_background_enabled"] = None

            save_settings()
            settings_win.destroy()
            print("Settings saved")

        tk.Button(settings_win, text="OK", command=save).grid(row=row, column=0, columnspan=3, pady=(8, 0))

        settings_win.update_idletasks()
        requested_width = settings_win.winfo_reqwidth() + 16
        requested_height = settings_win.winfo_reqheight() + 16
        settings_win.geometry(f"{requested_width}x{requested_height}")
        settings_win.minsize(requested_width, requested_height)

        def save_from_keyboard(_event=None):
            save()
            return "break"

        settings_win.bind("<Return>", save_from_keyboard)
        settings_win.bind("<KP_Enter>", save_from_keyboard)


if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()
