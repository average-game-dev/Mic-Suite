# TODO
write an md file explaining the scripts:

## `mic.py`
`mic.py` directs the audio input of a microphone device to an audio output, such as the modified mic output.
## `sound_board.py`
`sound_board.py` plays sounds defined in `sounds.json` to two output devices, recently a FLAC cache has replaced the storage-hungry WAV cache and can be remade by passing `--cache delete`.
## `convert.py`
`covert.py` converts audio files en masse to WAV, however this script isn't used much anymore due to most scripts supporting all FFmpeg formats.
## `spliter.py`
`spliter.py` splits the output from an audio input (like VB-Cable or a physical loopback cable) to two audio outputs with caps-lock controlling the second output.
## `monitor.py`
`monitor.py` is a simple script that reads the output of an output device and puts an audio indicator on the top left of the screen.
## `player.py`
`player.py`, while still updated, is mostly replaced by `playerGUI.py`. Refer to its definition.
## `playerGUI.py`
`playerGUI.py` (and without a GUI `player.py`) give a way to automatically play music defined in `playlists.json`. The numpad controls include (while NUMLOCK is active and `del` is pressed)
- PAUSE: NUMPAD8
- PREVIOUS_SONG: NUMPAD7
- NEXT_SONG NUMPAD9
- SEEK -10s: NUMPAD4
- SEEK -30s: NUMPAD1
- SEEK +10s: NUMPAD6
- SEEK +30s: NUMPAD3
- VOLUME_UP: NUMPAD5
- VOLUME_DOWN: NUMPAD2
- TOGGLE_SHUFFLE: NUMPAD/
- TOGGLE_RANDOM_ANY: NUMPAD*  
CLI commands are also avaliable.
## `url_player.py`
## `voice.py`
## `gpt2.py`
## `voicerec.py`
## `cookies_export.py`