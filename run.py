"""
Context-Aware Smart LLM Switching - Root Project Runner.
Delegates to backend runner and ensures seamless imports across project root.
"""

from pathlib import Path
import sys

# Ensure backend and root are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.run import main

if __name__ == "__main__":
    main()
