"""Entry point for hosts that look for `main:app` at the service root (Vercel)."""

from api.main import app

__all__ = ["app"]
