#!/usr/bin/env python3
"""Switchboard — team inbox, staffing and job scheduling. Double-click or run:

    python switchboard.py            # http://localhost:5050, opens your browser
    python switchboard.py --demo     # first time only: build a demo workspace to explore
    python switchboard.py --lan      # let other computers on your network connect

Data (database, attachments) lives in ./switchboard_data unless SWITCHBOARD_DATA_DIR
is set. Same thing as `pps switchboard run`.
"""

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Switchboard")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--lan", action="store_true", help="listen on all network interfaces")
    parser.add_argument("--demo", action="store_true", help="seed a demo workspace if the database is empty")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    from werkzeug.serving import run_simple

    from pps_tools.switchboard import db
    from pps_tools.switchboard.app import create_app
    from pps_tools.switchboard.seed import DEMO_PASSWORD, seed_demo

    app = create_app()
    if args.demo and not db.scalar("SELECT COUNT(*) FROM users"):
        seed_demo()
        print(f"Demo workspace created. Sign in as morgan@pps.demo / {DEMO_PASSWORD}")
    url = f"http://localhost:{args.port}"
    print(f"Switchboard running at {url} — press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    run_simple("0.0.0.0" if args.lan else "127.0.0.1", args.port, app, threaded=True)


if __name__ == "__main__":
    main()
