"""Development entry point.

    python3 -m part4.run

Serves on PART4_HOST:PART4_PORT (127.0.0.1:5055 by default). This is
Flask's development server, which is appropriate for a course
demonstration on localhost and is not a production deployment.
"""

from __future__ import annotations

from .app import create_app
from .app.config import CONFIG


def main() -> None:
    app = create_app()
    print(f"Part IV application on http://{CONFIG.host}:{CONFIG.port}")
    app.run(host=CONFIG.host, port=CONFIG.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
