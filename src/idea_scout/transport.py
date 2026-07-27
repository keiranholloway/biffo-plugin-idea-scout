"""The real ``Transport`` for the HTTP CoreGateway — the only piece that touches
the network (ADR-0017 §3/§5).

Every call to Core's internal API is **dual-authenticated**: SigV4-signed as this
plugin's Lambda role (via the SDK's ``SignedCoreClient``, so Core's
``require_service_principal`` accepts it) *and* carrying the founder's Cognito
token in ``X-Biffo-User-Token``, which Core re-verifies to establish identity and
owner-scope. The plugin's own ingress already verified that token to admit the
request; forwarding it lets Core be the authority.

Built by subclassing ``SignedCoreClient`` to reuse its signing verbatim, adding
only: arbitrary methods (owner-data updates are ``PATCH``, which the base client
lacks), the forwarded-user header, and the 404 -> ``CoreNotFoundError`` mapping
the adapter's owner-scoped reads rely on.

This is a deliberate copy of the Ideation Engine's ``transport.py`` — the two
plugins have no shared package, and this file is the narrowest possible piece to
duplicate rather than inventing a second way to authenticate.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from biffo_plugin_sdk import SignedCoreClient

from .adapter import CoreHttpError, CoreNotFoundError

#: Mirrors Core's ``middleware/forwarded_user.FORWARDED_USER_HEADER`` — keep in step.
FORWARDED_USER_HEADER = "X-Biffo-User-Token"


class CoreTransport(SignedCoreClient):
    """A SigV4-signed transport that also forwards the founder's token and maps
    Core's responses to the adapter's contract. Constructed per founder request."""

    def __init__(self, *, founder_token: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._founder_token = founder_token

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """The adapter's :class:`~idea_scout.adapter.Transport` seam."""
        return await self._send(method, path, params=params, json_body=json)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = self._url(path)
        if params:
            url = f"{url}?{urlencode(params)}"
        body = json.dumps(json_body).encode() if json_body is not None else None
        headers = self._sign(method, url, body)
        # Forwarded after signing: an unsigned header is fine (SigV4 verifies only
        # the signed set), and Core reads it separately to re-verify the founder.
        headers[FORWARDED_USER_HEADER] = self._founder_token
        response = await self._client.request(method, url, headers=headers, content=body)
        if response.status_code == 404:
            raise CoreNotFoundError(f"{method} {path} -> 404")
        if response.status_code >= 400:
            raise CoreHttpError(f"{method} {path} -> {response.status_code}: {response.text[:500]}")
        return self._parse_json(response)
