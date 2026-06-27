import sys
from pathlib import Path

# Make 'servicenow_mcp' importable as a package when running pytest
# from within the project directory, without requiring pip install.
sys.path.insert(0, str(Path(__file__).parent.parent))
