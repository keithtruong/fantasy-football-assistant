"""Local dev server for the draft tool.

Usage:
    python -m scripts.run_app
"""

from ffassistant.api import create_app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5050)
