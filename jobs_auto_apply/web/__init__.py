"""Web dashboard add-on for the existing jobs-auto-apply bot.

This package does not reimplement any bot behaviour. It is a thin control and
reporting surface over the modules that already exist:

* discovery  -> ``jobs_auto_apply.cli._review`` (collect -> filter -> enrich -> queue)
* review     -> ``data/review/<platform>.json`` (the same queue ``review`` writes)
* apply      -> ``jobs_auto_apply.cli._apply_reviewed`` (approved items only)
* history    -> ``data/applied_jobs.json`` (+ ``applied_report``)
* failures   -> ``data/technical_failures.json``

The CLI keeps working exactly as before; the dashboard is an additional entry
point (``python main.py web``).
"""

from __future__ import annotations

__all__ = ["create_app"]


def create_app(config_path):
    """Lazy re-export so importing this package never pulls in FastAPI."""
    from .app import create_app as _create_app

    return _create_app(config_path)
