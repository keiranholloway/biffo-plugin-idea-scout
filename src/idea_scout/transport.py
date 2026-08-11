"""The real ``Transport`` for the HTTP CoreGateway — the only piece that touches
the network (ADR-0017 §3/§5).

Every call to Core's internal API is **dual-authenticated**: SigV4-signed as this
plugin's Lambda role (via the SDK's ``PrincipalCoreClient``, so Core's
``require_service_principal`` accepts it) *and* carrying the founder's Cognito
token in ``X-Biffo-User-Token``, which Core re-verifies to establish identity and
owner-scope. The plugin's own ingress already verified that token to admit the
request; forwarding it lets Core be the authority.

``PrincipalCoreClient`` (biffo-plugin-sdk >=1.3, biffo-template#1490) folds the
forwarded-user header in *before* signing by overriding ``_sign`` — the single
choke point every verb passes through — so there is no call site that can add it
after signing and get it wrong. This file used to hand-roll that mechanism
itself (a deliberate copy of the Ideation Engine's own copy, since the two
plugins had no shared package); both are now consolidated onto the SDK class.
What remains here is only this adapter's own vocabulary: mapping the SDK's
``BiffoAPIError`` to this plugin's ``CoreNotFoundError``/``CoreHttpError``
contract, which callers throughout ``adapter.py`` catch by type.
"""

from __future__ import annotations

from typing import Any

from biffo_plugin_sdk import BiffoAPIError, PrincipalCoreClient

from .adapter import CoreHttpError, CoreNotFoundError

#: Mirrors Core's ``middleware/forwarded_user.FORWARDED_USER_HEADER`` — kept for
#: any external reference; the SDK's own constant of the same name is what
#: ``PrincipalCoreClient`` actually signs with.
FORWARDED_USER_HEADER = "X-Biffo-User-Token"


class CoreTransport(PrincipalCoreClient):
    """A SigV4-signed transport that forwards the founder's token (via the SDK's
    ``PrincipalCoreClient``) and maps Core's responses to the adapter's
    contract. Constructed per founder request."""

    def __init__(self, *, founder_token: str, **kwargs: Any) -> None:
        super().__init__(founder_token, **kwargs)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """The adapter's :class:`~idea_scout.adapter.Transport` seam."""
        try:
            return await self._send(method, path, params=params, json_body=json)
        except BiffoAPIError as exc:
            if exc.status_code == 404:
                raise CoreNotFoundError(f"{method} {path} -> 404") from exc
            detail = str(exc.body if exc.body is not None else exc.detail)[:500]
            raise CoreHttpError(f"{method} {path} -> {exc.status_code}: {detail}") from exc
