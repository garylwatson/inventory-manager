from pathlib import Path

from .app import main

if __name__ == "__main__":
    raise SystemExit(main(Path("config.yaml")))
