import os
import sounddevice as sd
import soundfile as sf
import numpy as np
import threading
import subprocess
import time
import json
from PySide6.QtWidgets import (
    QWidget, QLabel, QSlider, QComboBox, QPushButton,
    QHBoxLayout, QVBoxLayout, QApplication
)
from PySide6.QtCore import Qt, QSize, QTimer
import random
import sys

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
def ffmpeg_resample_and_normalize(input_file, output_file, target_sr=48000):
    temp_resampled = output_file.replace("_normalized.wav", "_resampled.wav")
    subprocess.run([
        "ffmpeg", "-y", "-i", input_file,
        "-ar", str(target_sr), "-ac", "2", "-c:a", "pcm_f32le", temp_resampled
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([
        "ffmpeg", "-y", "-i", temp_resampled,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ar", str(target_sr), "-ac", "2", "-c:a", "pcm_f32le", output_file
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.remove(temp_resampled)

def prepare_audio(file):
    base, ext = os.path.splitext(file)
    base = base.replace("_48000hz_normalized", "")
    temp_file = f"{base}_{stream_sr}hz_normalized.wav"
    if not os.path.exists(temp_file):
        print(f"[QUEUE] Resampling and normalizing: {file}")
        ffmpeg_resample_and_normalize(file, temp_file, stream_sr)
    return temp_file

def load_audio(file):
    data, sr = sf.read(file, dtype='float32')
    if data.ndim == 1:
        data = np.column_stack([data, data])
    if sr != stream_sr:
        raise RuntimeError(f"Sample rate mismatch: {sr} != {stream_sr}")
    return data

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
    file = prepare_audio(current_playlist[index])
    data = load_audio(file)
    with playing_lock:
        playing_song["data"] = data
        playing_song["pos"] = 0
        playing_song["name"] = os.path.basename(file)
    preload_next(index)

def preload_next(index):
    if not current_playlist or random_any_mode:
        return
    next_index = (index + 1) % len(current_playlist)
    file = prepare_audio(current_playlist[next_index])
    data = load_audio(file)
    with playing_lock:
        playing_song["preloaded"] = {
            "data": data,
            "name": os.path.basename(file),
            "index": next_index
        }

def play_next():
    global current_index
    if random_any_mode:
        all_tracks = [t for plist in playlists.values() for t in plist]
        if not all_tracks:
            return
        choice = random.choice(all_tracks)
        file = prepare_audio(choice)
        data = load_audio(file)
        with playing_lock:
            playing_song["data"] = data
            playing_song["pos"] = 0
            playing_song["name"] = os.path.basename(file)
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
                self.status_label.setText(f"{self.current_playlist_name} | {playing_song['name']} "
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