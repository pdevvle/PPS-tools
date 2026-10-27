"""Shared fixtures for the Marketing Hub tests."""

import time

import pytest

from pps_tools.marketing.config import MarketingSettings
from pps_tools.marketing.store import Store


@pytest.fixture
def settings(tmp_path):
    return MarketingSettings(db_path=tmp_path / "marketing.db", base_url="http://localhost:5050", demo="off")


@pytest.fixture
def store(settings):
    return Store(settings.db_path)


def connect(store, platform, **creds):
    """Store a connection with a token that won't expire during the test."""
    data = {"access_token": "token-123", "expires_at": time.time() + 3600}
    data.update(creds)
    store.save_connection(platform, data, profile={})
    return data
