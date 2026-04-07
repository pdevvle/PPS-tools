"""YAML configuration loader."""

from pathlib import Path

import yaml

_CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def _load_yaml(filename: str) -> dict:
    path = _CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def get_competitors() -> dict:
    """Load competitor definitions from config."""
    return _load_yaml("competitors.yaml").get("competitors", {})


def get_products() -> dict:
    """Load product definitions from config."""
    return _load_yaml("products.yaml").get("products", {})


def get_settings() -> dict:
    """Load application settings from config."""
    return _load_yaml("settings.yaml")


def get_config_dir() -> Path:
    """Return the config directory path."""
    return _CONFIG_DIR
