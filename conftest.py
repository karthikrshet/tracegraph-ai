# conftest.py — shared pytest fixtures
import sys
from pathlib import Path

# Ensure app module is importable
sys.path.insert(0, str(Path(__file__).parent))
