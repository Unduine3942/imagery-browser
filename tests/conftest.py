"""
pytest configuration for Imagery Browser tests.

Provides fixtures and setup for mocking arcpy and other external dependencies.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to sys.path so imports work
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Mock arcpy before any imports that might use it
sys.modules['arcpy'] = MagicMock()
