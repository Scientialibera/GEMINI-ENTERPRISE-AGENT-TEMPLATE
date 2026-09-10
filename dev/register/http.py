"""Authenticated JSON requests and pagination for registration APIs."""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import google.auth
import google.auth.transport.requests
import requests

REQUEST_TIMEOUT_SECONDS = 60
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def request(method: str, url: str, project_id: str, payload=None) -> dict[str, object]:
    credentials, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
    credentials.refresh(google.auth.transport.requests.Request())
    response = requests.request(
        method,
        url,
        json=payload,
        headers={"Authorization": f"Bearer {credentials.token}", "X-Goog-User-Project": project_id},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if not response.ok:
        raise SystemExit(f"{method} {url} failed with HTTP {response.status_code}: {response.text}")
    return response.json() if response.content else {}


def iter_resources(url: str, project_id: str, collection: str) -> Iterator[dict[str, object]]:
    """Keep the original query parameters while following every continuation token."""
    parts = urlsplit(url)
    parameters = dict(parse_qsl(parts.query, keep_blank_values=True))
    seen = set()
    while True:
        page_url = urlunsplit(parts._replace(query=urlencode(parameters)))
        page = request("GET", page_url, project_id)
        yield from page.get(collection, []) or []
        token = page.get("nextPageToken")
        if not token:
            return
        if not isinstance(token, str) or token in seen:
            raise RuntimeError("The registration API returned an invalid continuation token.")
        seen.add(token)
        parameters["pageToken"] = token
