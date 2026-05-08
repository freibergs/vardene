"""HTTP API + minimalist frontend for the morphology engine.

Run via:
    python -m vardene.api                # default 127.0.0.1:5000
    python -m vardene.api --port 8080
"""

from vardene.api.app import create_app

__all__ = ["create_app"]
