import os
import sounddevice as sd
import soundfile as sf
import numpy as np
import threading
import subprocess
import time
import json
import keyboard
from keymods import is_numlock_on
from PySide6.QtWidgets import (
    QWidget, QLabel, QSlider, QComboBox, QPushButton,
    QHBoxLayout, QVBoxLayout, QApplication
)
from PySide6.QtCore import Qt, QSize, QTimer
from mutagen import File as MutagenFile
from rich import print
import random
import sys

color = {
    "red": {
        "start": '<span style="color:red">',
        "end": '</span>'
    },
    "white": {
        "start": '<span style="color:white">',
        "end": '</span>'
    },
    "green": {
        "start": '<span style="color:green">',
        "end": '</span>'
    },
    "blue": {
        "start": '<span style="color:blue">',
        "end": '</span>'
    }
}

# --------------------------
# Settings
# --------------------------
stream_sr = 48000
stream_channels = 2
blocksize = 1024
master_gain = 1.0
gain_step = 0.05

playlist_json = "playlists.json"  # JSON file with playlists
shuffle_mode = False
random_any_mode = False
status_enabled = False

# --------------------------
# Playback state
# --------------------------
paused = False
playing_song = {"data": None, "pos": 0, "name": "", "preloaded": None}
playing_lock = threading.Lock()
current_playlist = []
current_playlist_name = None
current_index = 0
playlists = {}

# --------------------------
# Audio helpers
# --------------------------
def get_track_info(file, default_title="Unknown Track"):
    """
    Reads track title and artist from audio files (wav, mp3, flac, m4a, ogg).
    Returns a tuple: (title, artist)
    
    - default_title: used if the track title is missing
    - artist defaults to "UNKNOWN"
    """
    audio = MutagenFile(file, easy=True)
    title = default_title
    artist = "UNKNOWN"

    if audio is not None:
        # 'title' and 'artist' are standardized in EasyID3/EasyTags
        if "title" in audio and audio["title"]:
            title = audio["title"][0]
        if "artist" in audio and audio["artist"]:
            artist = audio["artist"][0]

    return {"title":title, "artist":artist}

def load_audio_ffmpeg(file):
    """
    Load audio via ffmpeg and return stereo float32 NumPy array.
    
    WAV:
        - resample to target_sr
        - loudness normalize
    Non-WAV:
        - resample only (no loudnorm)
    """

    ext = os.path.splitext(file)[1].lower()

    # Base ffmpeg args
    cmd = [
        "ffmpeg",
        "-i", file,
        "-ar", str(stream_sr),
        "-ac", "2",
    ]

    # Apply loudness normalization ONLY for WAVs
    if ext == ".wav":
        cmd += [
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11"
        ]

    # Output raw float32 PCM to stdout
    cmd += [
        "-f", "f32le",
        "pipe:1"
    ]

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True
    )

    raw = proc.stdout

    # Convert to NumPy array
    data = np.frombuffer(raw, dtype=np.float32).copy()

    # Ensure stereo
    if data.size % 2 != 0:
        raise RuntimeError("Audio stream is not stereo-aligned")

    data = data.reshape(-1, 2)
    info = get_track_info(file, os.path.basename(file))
    return info, data

def format_time(seconds):
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"

# --------------------------
# Playlist system
# --------------------------
def load_playlists_from_json(json_file):
    global playlists
    if not os.path.exists(json_file):
        print(f"[ERROR] Playlist JSON '{json_file}' not found.")
        return
    with open(json_file, "r", encoding="utf-8") as f:
        raw = json.load(f)

    playlists.clear()
    for name, content in raw.items():
        if isinstance(content, dict) and "folder" in content:
            folder = content["folder"]
            if os.path.exists(folder):
                tracks = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                          if f.lower().endswith(('.wav', '.flac', '.mp3', '.m4a'))]
                if tracks:
                    playlists[name] = tracks
        elif isinstance(content, list):
            tracks = [f for f in content if os.path.exists(f) and f.lower().endswith(('.wav', '.flac', '.mp3', '.m4a'))]
            if tracks:
                playlists[name] = tracks

def select_playlist(name):
    global current_playlist, current_playlist_name, current_index
    if name not in playlists:
        print(f"[ERROR] Playlist '{name}' not found.")
        return
    current_playlist = playlists[name]
    current_playlist_name = name
    current_index = 0
    queue_song(current_index)

def queue_song(index):
    global playing_song
    if not current_playlist:
        return
    if shuffle_mode and not random_any_mode:
        index = random.randint(0, len(current_playlist) - 1)
    info, data = load_audio_ffmpeg(current_playlist[index])
    with playing_lock:
        playing_song["data"] = data
        playing_song["pos"] = 0
        playing_song["name"] = info["title"]
        playing_song["path"] = current_playlist[index]
    preload_next(index)

def preload_next(index):
    if not current_playlist or random_any_mode:
        return
    next_index = (index + 1) % len(current_playlist)
    info, data = load_audio_ffmpeg(current_playlist[next_index])
    with playing_lock:
        playing_song["preloaded"] = {
            "data": data,
            "name": info["title"],
            "path": current_playlist[next_index],
            "index": next_index
        }

def play_next():
    global current_index
    if random_any_mode:
        all_tracks = [t for plist in playlists.values() for t in plist]
        if not all_tracks:
            return
        choice = random.choice(all_tracks)
        info, data = load_audio_ffmpeg(choice)
        with playing_lock:
            playing_song["data"] = data
            playing_song["pos"] = 0
            playing_song["name"] = info["title"]
            playing_song["path"] = choice
        return
    if shuffle_mode:
        current_index = random.randint(0, len(current_playlist) - 1)
    else:
        current_index = (current_index + 1) % len(current_playlist)
    queue_song(current_index)

def play_prev():
    global current_index
    current_index = (current_index - 1) % len(current_playlist)
    queue_song(current_index)

def toggle_pause():
    global paused
    paused = not paused

def seek_seconds(seconds):
    global playing_song
    need_next = False
    with playing_lock:
        if playing_song["data"] is None:
            return
        new_pos = playing_song["pos"] + int(seconds * stream_sr)
        if new_pos < 0:
            playing_song["pos"] = 0
        elif new_pos >= playing_song["data"].shape[0]:
            need_next = True
        else:
            playing_song["pos"] = new_pos
    if need_next:
        play_next()

def change_volume(delta):
    global master_gain
    master_gain = max(0.0, master_gain + delta)

# --------------------------
# Playback loop
# --------------------------
def playback_loop(device1, device2):
    global playing_song, paused
    with sd.OutputStream(device=device1, channels=stream_channels,
                         samplerate=stream_sr, blocksize=blocksize) as s1, \
         sd.OutputStream(device=device2, channels=stream_channels,
                         samplerate=stream_sr, blocksize=blocksize) as s2:
        while True:
            if playing_song["data"] is None or paused:
                time.sleep(0.05)
                continue

            need_next = False
            with playing_lock:
                pos = playing_song["pos"]
                data = playing_song["data"]
                chunk = data[pos:pos+blocksize]
                chunk_len = chunk.shape[0]

                if chunk_len < blocksize:
                    pad = np.zeros((blocksize - chunk_len, stream_channels), dtype='float32')
                    chunk = np.vstack([chunk, pad])

                chunk *= master_gain
                playing_song["pos"] += chunk_len

                if playing_song["pos"] >= data.shape[0]:
                    need_next = True

            s1.write(chunk)
            s2.write(chunk)

            if need_next:
                play_next()

# --------------------------
# Control loop (numpad)
# --------------------------
def control_loop():
    global shuffle_mode, random_any_mode
    while True:
        if keyboard.is_pressed(83):  # So that music player operations don't act weirdly with normal numpad functions.
            if is_numlock_on() and keyboard.is_pressed('num 7'):
                play_prev()
                while keyboard.is_pressed('num 7'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 8'):
                toggle_pause()
                while keyboard.is_pressed('num 8'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 9'):
                play_next()
                while keyboard.is_pressed('num 9'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num /'):
                shuffle_mode = not shuffle_mode
                print("Shuffle mode:", shuffle_mode)
                while keyboard.is_pressed('num /'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num *'):
                random_any_mode = not random_any_mode
                print("Random-anywhere mode:", random_any_mode)
                while keyboard.is_pressed('num *'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 4'):
                seek_seconds(-10)
                while keyboard.is_pressed('num 4'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 1'):
                seek_seconds(-30)
                while keyboard.is_pressed('num 1'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 6'):
                seek_seconds(10)
                while keyboard.is_pressed('num 6'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 3'):
                seek_seconds(30)
                while keyboard.is_pressed('num 3'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 5'):
                change_volume(gain_step)
                while keyboard.is_pressed('num 5'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num 2'):
                change_volume(-gain_step)
                while keyboard.is_pressed('num 2'): time.sleep(0.05)
            elif is_numlock_on() and keyboard.is_pressed('num -'):
                status_enable = not status_enable
        time.sleep(0.05)

# --------------------------
# GUI
# --------------------------
class PlayerGUI(QWidget):
    def __init__(self, playlists):
        super().__init__()
        self.playlists = playlists
        self.playlist_names = list(playlists.keys())
        self.current_playlist = []
        self.current_playlist_name = None
        self.shuffle_mode = False
        self.random_any_mode = False

        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout()  # main horizontal layout

        # Left side (controls)
        left_layout = QVBoxLayout()

        # Status label
        self.status_label = QLabel("Nothing playing")
        self.status_label.setObjectName("StatusLabel")
        left_layout.addWidget(self.status_label)

        # Progress slider
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setObjectName("ProgressSlider")
        self.progress_slider.setMinimum(0)
        self.progress_slider.setMaximum(1000)
        self.progress_slider.setValue(0)
        self.progress_slider.setEnabled(False)
        self.progress_slider.sliderReleased.connect(self.slider_released)
        left_layout.addWidget(self.progress_slider)

        # Playlist dropdown
        self.playlist_combo = QComboBox()
        self.playlist_combo.setObjectName("PlaylistDropdown")
        self.playlist_combo.addItem("-- Select Playlist --")
        self.playlist_combo.addItems(self.playlist_names)
        self.playlist_combo.currentTextChanged.connect(self.select_playlist)
        left_layout.addWidget(self.playlist_combo)

        # Device dropdowns with placeholders
        all_devs = sd.query_devices()
        self.devices = [f"[{i}] {d['name']} (hostapi={d['hostapi']})"
                        for i, d in enumerate(all_devs) if d['max_output_channels'] > 0]

        self.device1_combo = QComboBox()
        self.device1_combo.setObjectName("DeviceDropdown1")
        self.device1_combo.addItem("-- Select Device 1 --")
        self.device1_combo.addItems(self.devices)
        left_layout.addWidget(self.device1_combo)

        self.device2_combo = QComboBox()
        self.device2_combo.setObjectName("DeviceDropdown2")
        self.device2_combo.addItem("-- Select Device 2 --")
        self.device2_combo.addItems(self.devices)
        left_layout.addWidget(self.device2_combo)

        # Start playback button
        self.start_btn = QPushButton("Start Playback")
        self.start_btn.setObjectName("StartPlaybackButton")
        self.start_btn.clicked.connect(self.start_playback)
        left_layout.addWidget(self.start_btn)

        # Control buttons
        hbox = QHBoxLayout()

        self.prev_btn = QPushButton("Prev")
        self.prev_btn.setObjectName("PrevButton")
        self.prev_btn.clicked.connect(self.prev)
        hbox.addWidget(self.prev_btn)

        self.play_pause_btn = QPushButton("Pause/Play")
        self.play_pause_btn.setObjectName("PlayToggleButton")
        self.play_pause_btn.clicked.connect(self.toggle_pause)
        hbox.addWidget(self.play_pause_btn)

        self.next_btn = QPushButton("Next")
        self.next_btn.setObjectName("NextButton")
        self.next_btn.clicked.connect(self.next)
        hbox.addWidget(self.next_btn)

        left_layout.addLayout(hbox)

        # Shuffle / Random-any
        self.shuffle_btn = QPushButton(f"Shuffle: {'ON' if self.shuffle_mode else 'OFF'}")
        self.shuffle_btn.setObjectName("ShuffleModeToggleButton")
        self.shuffle_btn.clicked.connect(self.toggle_shuffle)
        left_layout.addWidget(self.shuffle_btn)

        self.random_any_btn = QPushButton(f"Random-any: {'ON' if self.random_any_mode else 'OFF'}")
        self.random_any_btn.setObjectName("RandomAnyToggleButton")
        self.random_any_btn.clicked.connect(self.toggle_random_any)
        left_layout.addWidget(self.random_any_btn)

        main_layout.addLayout(left_layout)

        # Right side (volume slider)
        right_layout = QVBoxLayout()
        right_layout.setObjectName("RightLayout")

        self.volume_label = QLabel("Volume")
        self.volume_label.setObjectName("VolumeLabel")
        self.volume_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        right_layout.addWidget(self.volume_label)

        # Horizontal wrapper to center slider
        h_slider_layout = QHBoxLayout()
        h_slider_layout.setObjectName("HorSliderLayout")
        h_slider_layout.addStretch()

        self.volume_slider = QSlider(Qt.Orientation.Vertical)
        self.volume_slider.setObjectName("VolumeSlider")
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(int(master_gain * 100))
        self.volume_slider.valueChanged.connect(self.change_volume)
        h_slider_layout.addWidget(self.volume_slider)

        h_slider_layout.addStretch()
        right_layout.addLayout(h_slider_layout, stretch=1)

        main_layout.addLayout(right_layout)

        self.setLayout(main_layout)
        self.setWindowTitle("AVPyPlay")
        self.resize(QSize(400,250))
        self.show()

        self.control_thread = threading.Thread(target=control_loop, daemon=True)
        self.control_thread.start()

        # Timer for status update
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(500)

    # --------------------------
    # GUI callbacks
    # --------------------------
    def select_playlist(self, name):
        if name.startswith("--"):
            self.current_playlist_name = None
            self.current_playlist = []
            return

        if name in self.playlists:
            placeholder_index = self.playlist_combo.findText("-- Select Playlist --")
            if placeholder_index != -1:
                self.playlist_combo.removeItem(placeholder_index)

            self.current_playlist_name = name
            self.current_playlist = self.playlists[name]

            global current_playlist, current_playlist_name, current_index
            current_playlist = self.playlists[name]
            current_playlist_name = name
            current_index = 0

            if current_playlist:
                queue_song(current_index)
                print(f"Selected playlist: {name}, first song queued")

    def start_playback(self):
        # Ensure playlist and devices are selected
        if not current_playlist:
            print("No playlist selected!")
            return
        if self.device1_combo.currentText().startswith("--") or \
           self.device2_combo.currentText().startswith("--"):
            print("Select both output devices first!")
            return

        dev1_idx = int(self.device1_combo.currentText().split(']')[0][1:])
        dev2_idx = int(self.device2_combo.currentText().split(']')[0][1:])
        
        threading.Thread(target=playback_loop, args=(dev1_idx, dev2_idx), daemon=True).start()
        print("Playback started")

    def prev(self):
        play_prev()
        print("Prev pressed")

    def next(self):
        play_next()
        print("Next pressed")

    def toggle_pause(self):
        toggle_pause()
        print("Toggled pause")

    def toggle_shuffle(self):
        self.shuffle_mode = not self.shuffle_mode
        global shuffle_mode
        shuffle_mode = self.shuffle_mode
        self.shuffle_btn.setText(f"Shuffle: {'ON' if self.shuffle_mode else 'OFF'}")
        print("Shuffle toggled", self.shuffle_mode)

    def toggle_random_any(self):
        self.random_any_mode = not self.random_any_mode
        global random_any_mode
        random_any_mode = self.random_any_mode
        self.random_any_btn.setText(f"Random-any: {'ON' if self.random_any_mode else 'OFF'}")
        print("Random-any toggled", self.random_any_mode)

    def update_status(self):
        with playing_lock:
            if playing_song["data"] is not None:
                pos = playing_song["pos"] / stream_sr
                total = playing_song["data"].shape[0] / stream_sr
                self.status_label.setText(f"{color['red']['start']}{self.current_playlist_name}{color['red']['end']}/{color['green']['start']}{playing_song['name']}{color['green']['end']} "
                                          f"{format_time(pos)}/{format_time(total)}")
                self.progress_slider.setEnabled(True)
                self.progress_slider.setValue(int((pos / total) * 1000))
            else:
                self.status_label.setText("Nothing playing")
                self.progress_slider.setEnabled(False)
                self.progress_slider.setValue(0)

    def slider_released(self):
        if playing_song["data"] is None:
            return
        fraction = self.progress_slider.value() / 1000
        new_pos = int(fraction * playing_song["data"].shape[0])
        with playing_lock:
            playing_song["pos"] = new_pos

    def change_volume(self, value):
        global master_gain
        master_gain = value / 100.0
# --------------------------
# Run GUI
# --------------------------
if __name__ == "__main__":
    load_playlists_from_json(playlist_json)  # populate global playlists
    if not playlists:
        print("[ERROR] No playlists found. Exiting.")
        sys.exit(1)

    app = QApplication(sys.argv)

    # Safely load and apply QSS stylesheet
    with open("source/style.qss", "r") as f:
        app.setStyleSheet(f.read())

    gui = PlayerGUI(playlists )  # pass global playlists
    sys.exit(app.exec())