# TODO
write a md file explaining the scripts:

## `mic.py`
`mic.py` applies effects to an input microphone stream and outputs it to an output device.
## `sound_board.py`
`sound_board.py` plays sounds defined in `sounds.json` to two output devices, recently a FLAC cache has replaced the storage-hungry WAV cache and can be remade by passing `--cache delete`.
The following combinations are included for use within the soundboard:
- `Plus`: +10
- `Minus`: +20
- `Enter`: +30
- `Plus+Minus`: +40
- `Minus+Enter`: +50
- `Plus+Enter`: +60
- `Plus+Minus+Enter`: +70
## `convert.py`
`covert.py` converts audio files en masse to WAV, however this script isn't used much anymore due to most scripts supporting all FFmpeg formats.
## `spliter.py`
`spliter.py` splits the output from an audio input (like VB-Cable or a physical loopback cable) to two audio outputs with caps-lock controlling the second output.
## `monitor.py`
`monitor.py` is a simple script that reads the output of an output device and puts an audio indicator on the top left of the screen.
## `player.py`
~~`player.py`, while still updated, is mostly replaced by `playerGUI.py`. Refer to its definition.~~
`player.py` has been completely deprecated. It still exists, however is not updated. `player.py` has mostly been replaced by an external project: [Vanadium](https://github.com/average-game-dev/vanadium).
## `playerGUI.py`
`playerGUI.py` (and without a GUI `player.py`) give a way to automatically play music defined in `playlists.json`. The numpad controls include (while NUMLOCK is active and `del` is pressed)
- PAUSE: NUMPAD8
- PREVIOUS_SONG: NUMPAD7
- NEXT_SONG NUMPAD9
- SEEK -10s: NUMPAD4
- SEEK -30s: NUMPAD1
- SEEK +10s: NUMP1AD6
- SEEK +30s: NUMPAD3
- VOLUME_UP: NUMPAD5
- VOLUME_DOWN: NUMPAD2
- TOGGLE_SHUFFLE: NUMPAD/
- TOGGLE_RANDOM_ANY: NUMPAD*  
CLI commands are also avaliable.
## `url_player.py`
The `url_player.py` is mostly deprecated. In order to get all commands type `help`.
## `voice.py`
`voice.py` allows you to select two output devices and use SAPI5 speach generation to speak the user input words.
## `voice2.py`
`voice2.py` is the same as `voice.py`, however it runs your input text through ChatGPT-2 before speaking them.
## `voice3.py`
`voice3.py` is the same as `voice.py`, but it uses clips of words in `./words` instead of SAPI5 speach when available.
## `voicerec.py`
`voicerec.py` is the same as `voice.py`, but you hold the `` ` `` key to record your voice, and runs your speach through Google's SpeachRecognition and speaks detected words.
## `cookies_export.py`
`cookie_export.py` exports cookies from Firefox SQLite databases into Netscape Navigator style cookies.
###### ***Note:*** `cookies_export.py` is mostly deprecated and isn't updated. 