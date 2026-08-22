"""
Vercel Serverless Entry Point for TraceGraph AI FastAPI Application
"""
import os
import sys
from pathlib import Path

# Add project root to sys.path
ROOT_DIR = Path(__file__).parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# This module is Vercel's entry point. Mark the process explicitly instead of
# relying on Vercel's optional system environment-variable exposure.
os.environ.setdefault("TRACEGRAPH_SERVERLESS", "vercel")

from app.api.main import app
