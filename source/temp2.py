import os
import matplotlib.pyplot as plt
from sys import argv

def get_folder_sizes(path):
    sizes = {}
    for entry in os.scandir(path):
        if entry.is_file():
            sizes[entry.name] = entry.stat().st_size
        elif entry.is_dir():
            total = 0
            for root, _, files in os.walk(entry.path):
                for f in files:
                    fp = os.path.join(root, f)
                    if os.path.exists(fp):
                        total += os.path.getsize(fp)
            sizes[entry.name] = total
    return sizes

folder = argv[1]  # replace with your folder
sizes = get_folder_sizes(folder)

# Convert to human-readable sizes for labels (optional)
def sizeof_fmt(num, suffix='B'):
    for unit in ['','K','M','G','T']:
        if abs(num) < 1024.0:
            return f"{num:.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}P{suffix}"

labels = [f"{name}\n{sizeof_fmt(size)}" for name, size in sizes.items()]
values = list(sizes.values())

plt.figure(figsize=(8,8))
plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=140)
plt.title(f"Disk Usage in '{os.path.basename(folder)}'")
plt.show()
