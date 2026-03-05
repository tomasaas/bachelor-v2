"""
Flask application factory.
"""

from __future__ import annotations

import logging

from flask import Flask

log = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    from server.routes import bp
    app.register_blueprint(bp)

    log.info("Flask app created")
    return app
