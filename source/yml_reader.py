import yaml

def read(file: str):
    with open(file, "r") as f:
        data = yaml.safe_load(f)
    return data