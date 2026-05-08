"""HTTP API + minimalist frontend for the morphology engine.

Run via:
    python -m tezaurs.api                # default 127.0.0.1:5000
    python -m tezaurs.api --port 8080
"""

from tezaurs.api.app import create_app

__all__ = ["create_app"]
