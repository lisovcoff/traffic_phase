"""Shared paths and Windows setup for command-line validation tools."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare_worker_environment():
    """Avoid a blocking Windows WMI query in scientific-library imports."""
    if sys.platform == 'win32':
        import platform
        architecture = os.environ.get('PROCESSOR_ARCHITEW6432') or os.environ.get('PROCESSOR_ARCHITECTURE')
        if architecture:
            platform._get_machine_win32 = lambda: architecture
