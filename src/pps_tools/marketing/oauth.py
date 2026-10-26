"""Small OAuth helpers shared by the connectors: PKCE, URLs and OAuth 1.0a signing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import Mapping, Optional
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge) per RFC 7636."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def with_query(url: str, params: Mapping[str, object]) -> str:
    return f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"


def basic_auth(client_id: str, client_secret: str) -> dict:
    raw = f"{client_id}:{client_secret}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


# -- OAuth 1.0a (X still requires it for the Ads API) -----------------------------


def percent_encode(value: str) -> str:
    return quote(str(value), safe="~")


def oauth1_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    token: Optional[str] = None,
    token_secret: Optional[str] = None,
    params: Optional[Mapping[str, object]] = None,
    form: Optional[Mapping[str, object]] = None,
    extra_oauth: Optional[Mapping[str, str]] = None,
    nonce: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> str:
    """Build an RFC 5849 HMAC-SHA1 `Authorization: OAuth ...` header.

    `params` are query-string parameters and `form` url-encoded body fields;
    both are signed. JSON and multipart bodies are not part of the signature.
    """
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_version": "1.0",
    }
    if token:
        oauth["oauth_token"] = token
    if extra_oauth:
        oauth.update(extra_oauth)

    parts = urlsplit(url)
    base_url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))
    pairs = list(parse_qsl(parts.query, keep_blank_values=True))
    pairs += [(k, str(v)) for k, v in (params or {}).items() if v is not None]
    pairs += [(k, str(v)) for k, v in (form or {}).items() if v is not None]
    pairs += list(oauth.items())
    encoded = sorted((percent_encode(k), percent_encode(v)) for k, v in pairs)
    param_string = "&".join(f"{k}={v}" for k, v in encoded)
    base_string = "&".join([method.upper(), percent_encode(base_url), percent_encode(param_string)])
    key = f"{percent_encode(consumer_secret)}&{percent_encode(token_secret or '')}"
    signature = base64.b64encode(hmac.new(key.encode(), base_string.encode(), hashlib.sha1).digest()).decode()
    oauth["oauth_signature"] = signature
    return "OAuth " + ", ".join(f'{percent_encode(k)}="{percent_encode(v)}"' for k, v in sorted(oauth.items()))
