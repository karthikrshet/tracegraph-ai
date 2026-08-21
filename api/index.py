"""
Vercel Serverless Entry Point for TraceGraph AI FastAPI Application
"""
import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.api.main import app
