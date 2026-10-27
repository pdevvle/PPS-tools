"""Runtime configuration, read from the environment (and a .env file if present)."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 5050


@dataclass
class Config:
    data_dir: Path
    secret_key: str
    # Public URL the app is reachable at. Used for links in emails, Twilio webhook
    # signature checks, the chat widget snippet and calendar feeds.
    base_url: str = f"http://localhost:{DEFAULT_PORT}"
    testing: bool = False
    start_worker: bool = True
    # How many reverse proxies sit in front of the app. Their X-Forwarded-* headers
    # are trusted only when this is set; otherwise anyone could fake their IP.
    proxy_count: int = 0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "switchboard.db"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:  # pragma: no cover - python-dotenv is a dependency
            pass

        data_dir = overrides.pop("data_dir", None) or os.environ.get("SWITCHBOARD_DATA_DIR") or "switchboard_data"
        data_dir = Path(data_dir).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        secret = (
            overrides.pop("secret_key", None)
            or os.environ.get("SWITCHBOARD_SECRET_KEY")
            or _persistent_secret(data_dir)
        )
        base_url = (
            overrides.pop("base_url", None)
            or os.environ.get("SWITCHBOARD_BASE_URL")
            or f"http://localhost:{DEFAULT_PORT}"
        )
        if "proxy_count" not in overrides:
            try:
                overrides["proxy_count"] = max(0, int(os.environ.get("SWITCHBOARD_PROXY_COUNT") or 0))
            except ValueError:
                overrides["proxy_count"] = 0
        return cls(data_dir=data_dir, secret_key=secret, base_url=base_url.rstrip("/"), **overrides)


_current: Config | None = None


def set_current(config: Config) -> None:
    global _current
    _current = config


def current() -> Config:
    """The running app's config (usable outside a request, e.g. in the worker)."""
    if _current is None:
        raise RuntimeError("Switchboard app has not been created")
    return _current


def _persistent_secret(data_dir: Path) -> str:
    """Generate the session-signing key once and keep it next to the database, so
    restarts don't log everybody out."""
    path = data_dir / "secret_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_hex(32)
    path.write_text(key)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - e.g. Windows
        pass
    return key
