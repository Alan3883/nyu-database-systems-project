"""Flask application factory.

Server-rendered Jinja2 pages, no JavaScript framework, no build step. The
deliverable is a working database application; a single-page front end
would add a toolchain without adding evidence.

Error policy: a DomainError is a business outcome and is shown to the
user as a short message. Anything else is a defect, is logged with its
traceback, and reaches the user as a generic message with no internals.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from flask import Flask, render_template

from .config import CONFIG
from .services.errors import DomainError


def configure_logging() -> None:
    log_dir = CONFIG.log_path
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "part4_app.log", mode="a"),
            logging.StreamHandler(),
        ],
    )


def create_app() -> Flask:
    configure_logging()
    app = Flask(__name__)
    # Session key for flash messages only. Generated per process: no
    # secret is written to disk or to version control.
    app.config["SECRET_KEY"] = secrets.token_hex(32)
    app.config["JSON_SORT_KEYS"] = False

    from .routes import dashboard, ml_admin, policies, quotes, regional_context

    app.register_blueprint(dashboard.bp)
    app.register_blueprint(quotes.bp)
    app.register_blueprint(policies.bp)
    app.register_blueprint(regional_context.bp)
    app.register_blueprint(ml_admin.bp)

    @app.errorhandler(DomainError)
    def handle_domain_error(exc: DomainError):
        return render_template("error.html", title="Cannot continue",
                               message=str(exc)), 400

    @app.errorhandler(404)
    def handle_not_found(exc):  # noqa: ANN001
        return render_template("error.html", title="Not found",
                               message="That page does not exist."), 404

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        app.logger.exception("Unhandled error")
        return render_template(
            "error.html", title="Application error",
            message=("Something went wrong. The details were written to "
                     "logs/part4_app.log.")), 500

    @app.context_processor
    def inject_globals() -> dict:
        return {
            "app_name": "Insurance Quote & Regional Research Application",
            "part": "Database Systems Project Part IV",
        }

    return app


app = create_app()
