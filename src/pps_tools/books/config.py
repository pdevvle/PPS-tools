"""Settings from the environment (or a .env file).

    BOOKS_DATA_DIR        where the database, attachments and secret key live (./books-data)
    BOOKS_DATABASE_URL    SQLAlchemy URL; defaults to SQLite in the data dir
    BOOKS_SECRET_KEY      session signing key; generated and saved in the data dir if unset
    BOOKS_BASE_URL        public URL customers reach (for pay links in emails), e.g. https://books.example.com
    STRIPE_SECRET_KEY     sk_live_... / sk_test_... (or a restricted rk_ key)
    STRIPE_PUBLISHABLE_KEY
    STRIPE_WEBHOOK_SECRET whsec_... for /stripe/webhook
    SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD SMTP_FROM SMTP_TLS  outgoing email
    ANTHROPIC_API_KEY     optional: AI categorization and receipt reading
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("BOOKS_DATA_DIR", "books-data")))
    database_url: Optional[str] = field(default_factory=lambda: os.environ.get("BOOKS_DATABASE_URL"))
    secret_key: Optional[str] = field(default_factory=lambda: os.environ.get("BOOKS_SECRET_KEY"))
    base_url: Optional[str] = field(default_factory=lambda: os.environ.get("BOOKS_BASE_URL"))
    stripe_secret_key: Optional[str] = field(default_factory=lambda: os.environ.get("STRIPE_SECRET_KEY"))
    stripe_publishable_key: Optional[str] = field(default_factory=lambda: os.environ.get("STRIPE_PUBLISHABLE_KEY"))
    stripe_webhook_secret: Optional[str] = field(default_factory=lambda: os.environ.get("STRIPE_WEBHOOK_SECRET"))
    smtp_host: Optional[str] = field(default_factory=lambda: os.environ.get("SMTP_HOST"))
    smtp_port: int = field(default_factory=lambda: int(os.environ.get("SMTP_PORT", "587")))
    smtp_user: Optional[str] = field(default_factory=lambda: os.environ.get("SMTP_USER"))
    smtp_password: Optional[str] = field(default_factory=lambda: os.environ.get("SMTP_PASSWORD"))
    smtp_from: Optional[str] = field(default_factory=lambda: os.environ.get("SMTP_FROM"))
    smtp_tls: bool = field(default_factory=lambda: os.environ.get("SMTP_TLS", "1") not in ("0", "false", "no"))
    anthropic_api_key: Optional[str] = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY"))
    testing: bool = False
    max_upload_mb: int = 25

    def resolve(self) -> "Config":
        self.data_dir = Path(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite:///{(self.data_dir / 'books.db').resolve()}"
        if not self.secret_key:
            key_file = self.data_dir / "secret_key"
            if key_file.exists():
                self.secret_key = key_file.read_text().strip()
            else:
                self.secret_key = secrets.token_hex(32)
                key_file.write_text(self.secret_key)
                try:
                    os.chmod(key_file, 0o600)
                except OSError:  # pragma: no cover
                    pass
        return self

    @property
    def attachments_dir(self) -> Path:
        path = self.data_dir / "attachments"
        path.mkdir(parents=True, exist_ok=True)
        return path
