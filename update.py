import os
import sys
import shutil
import tempfile
import zipfile
import urllib.request


# -----------------------------
# CONFIG
# -----------------------------
REPO_OWNER = "average-game-dev"
REPO_NAME = "Mic-Suite"
BRANCH = "main"
TARGET_DIR = "."

PRESERVE_PATHS = [
    "sounds",
    "songs",
    "downloads",
    "playlists.json",
    "sounds.json",
]


# -----------------------------
# Helpers
# -----------------------------
def download_repo_zip(owner, repo, branch, dest_path):
    url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, dest_path)


def extract_zip(zip_path, extract_to):
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(extract_to)


def copy_preserved(src_root, backup_root):
    for rel_path in PRESERVE_PATHS:
        src = os.path.join(src_root, rel_path)
        dst = os.path.join(backup_root, rel_path)

        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)


def restore_preserved(backup_root, target_root):
    for rel_path in PRESERVE_PATHS:
        src = os.path.join(backup_root, rel_path)
        dst = os.path.join(target_root, rel_path)

        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)


def clear_directory(path):
    for name in os.listdir(path):
        full = os.path.join(path, name)
        if os.path.isdir(full):
            shutil.rmtree(full)
        else:
            os.remove(full)


# -----------------------------
# Main Update Logic
# -----------------------------
def main():
    target_dir = os.path.abspath(TARGET_DIR)

    if not os.path.isdir(target_dir):
        print("Target directory does not exist.")
        sys.exit(1)

    # Safety check
    if os.path.abspath(target_dir) in ["C:\\", "/"]:
        print("Refusing to operate on root directory.")
        sys.exit(1)

    temp_dir = tempfile.mkdtemp(prefix="repo_update_")
    backup_dir = tempfile.mkdtemp(prefix="repo_backup_")
    zip_path = os.path.join(temp_dir, "repo.zip")

    try:
        # Download
        download_repo_zip(REPO_OWNER, REPO_NAME, BRANCH, zip_path)

        # Extract
        extract_zip(zip_path, temp_dir)

        # GitHub zip extracts into folder like repo-branch
        extracted_root = None
        for name in os.listdir(temp_dir):
            full = os.path.join(temp_dir, name)
            if os.path.isdir(full) and name.startswith(f"{REPO_NAME}-"):
                extracted_root = full
                break

        if not extracted_root:
            print("Failed to locate extracted repo.")
            sys.exit(1)

        print("Backing up preserved files...")
        copy_preserved(target_dir, backup_dir)

        print("Clearing target directory...")
        clear_directory(target_dir)

        print("Copying new files...")
        for item in os.listdir(extracted_root):
            src = os.path.join(extracted_root, item)
            dst = os.path.join(target_dir, item)

            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        print("Restoring preserved files...")
        restore_preserved(backup_dir, target_dir)

        print("Update complete.")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        shutil.rmtree(backup_dir, ignore_errors=True)


if __name__ == "__main__":
    main()