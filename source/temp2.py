import yaml

with open("source/config.yml", "r") as f:
    config = yaml.safe_load(f)  # safe_load avoids executing arbitrary code

print(config)  # the whole YAML as a Python dict
print(config["playerGUI"]["windowSize"]["width"])  # access nested values
