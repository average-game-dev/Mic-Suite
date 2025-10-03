import threading
import subprocess

def worker():
    subprocess.run(["pip", "install", "pydantic"])

workers = {}

for i in range(1000):
    workers[f"worker{i}"] = threading.Thread(target=worker)

for index in range(len(workers)):
    workers[f"worker{index}"].start()
