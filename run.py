import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / ".vscode"))

from app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
