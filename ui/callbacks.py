"""
callbacks.py
------------
Thin compatibility wrapper for the feature-specific callback modules.
"""

from ui.callbacks_core import register_callbacks
from ui.callbacks_phase3 import register_phase3_callbacks

__all__ = ["register_callbacks", "register_phase3_callbacks"]
