import sys
import subprocess
import os
from sys import argv

if len(argv) == 2:
    ENV_DIR = argv[1]
else:
    ENV_DIR = "env"

AI_FLAG = (input("Enable AI packages? [y/n] (default: n)  ") == "y")

def create_env(path):
    if not os.path.exists(path):
        subprocess.check_call([sys.executable, "-m", "venv", path])
    else:
        print("Venv already exists")

def pip_install(packages):
    pip_exe = os.path.join(ENV_DIR, "Scripts" if os.name == "nt" else "bin", "pip")
    subprocess.check_call([pip_exe, "install"] + packages)

def get_packages():
    
    pkgs = [
        "numpy",
        "sounddevice",
        "PySide6",
        "soundfile",
        "keyboard",
        "yt-dlp",
        "requests",
        "rich",
        "fastapi",
        "uvicorn",
        "numba",
        "mutagen",
        "pyyaml",
        "comtypes"
    ]

    if AI_FLAG: # heavy packages only used for AI stuff
        pkgs.extend([
            "pyttsx3",
            "transformers",
            "SpeechRecognition"
        ])

    return pkgs


def main():
    create_env(ENV_DIR)
    pkgs = get_packages()
    pip_install(pkgs)
    print("Environment ready! Activate with:")
    if os.name == "nt":
        print(f".\\{ENV_DIR}\\Scripts\\activate.bat")
    else:
        print(f"source {ENV_DIR}/bin/activate")
        
    with open("sounds.json", "a"):
        pass
    with open("playlists.json", "a"):
        pass
    with open("word.json", "a"):
        pass
    os.makedirs("sounds", exist_ok=True)
    os.makedirs("songs", exist_ok=True)
    os.makedirs("words", exist_ok=True)

if __name__ == "__main__":
    main()