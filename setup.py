import sys
import subprocess
import os
from sys import argv

if len(argv) >= 2: ENV_DIR = argv[1]
else: ENV_DIR = None
if len(argv) >= 3: AI_FLAG = argv[2]
else: AI_FLAG = None 

def create_env(path):
    if not os.path.exists(path):
        subprocess.check_call([sys.executable, "-m", "venv", path])
    else:
        print("Venv already exists")

def pip_install(packages):
    pip_exe = os.path.join(ENV_DIR, "Scripts" if os.name == "nt" else "bin", "pip")
    for pkg in packages:
        subprocess.check_call([pip_exe, "install", pkg])

def get_packages():
    
    pkgs = [
        "numpy",
        "sounddevice",
        "PySide6",
        "soundfile",
        "keyboard",
        "yt-dlp"
    ]

    if AI_FLAG: # heavy packages only used for AI stuff
        pkgs.extend([
            "comtypes",
            "pyttsx3",
            "transformers",
            "SpeechRecognition"
        ])
    else: print("[Note] The user has implicitly disabled AI modules. Python scripts voice.py, voice2.py, and voicerec.py aren't able to be run!\n\n\tThe AI features can be enabled by rerunning this script with the second command argument set to a truthy value.")

    return pkgs


def main():
    create_env(ENV_DIR if ENV_DIR != None else "env")
    pkgs = get_packages()
    pip_install(pkgs)
    print("Environment ready! Activate with:")
    if os.name == "nt":
        print(f"{ENV_DIR}\\Scripts\\activate.bat")
    else:
        print(f"source {ENV_DIR}/bin/activate")
        
    with open("sounds.json", "a"):
        pass
    with open("playlists.json", "a"):
        pass


if __name__ == "__main__":
    main()

