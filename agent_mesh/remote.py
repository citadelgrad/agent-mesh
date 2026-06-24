import httpx
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent


class _GoogleCloudAuth(httpx.Auth):
    def __init__(self):
        self._creds = None

    def auth_flow(self, request):
        from google.auth import default
        from google.auth.transport.requests import Request as AuthRequest

        if self._creds is None:
            self._creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        if not self._creds.valid:
            self._creds.refresh(AuthRequest())
        request.headers["Authorization"] = f"Bearer {self._creds.token}"
        yield request


class AeRemoteAgent(RemoteA2aAgent):
    # ponytail: override _ensure_httpx_client only — httpx_client=None at init keeps ADK #3004 safe.
    # GoogleCloudAuth creds are lazy (None at init), so the unconstructed agent pickles cleanly.
    async def _ensure_httpx_client(self) -> httpx.AsyncClient:
        if not self._httpx_client:
            self._httpx_client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout=self._timeout),
                auth=_GoogleCloudAuth(),
            )
            self._httpx_client_needs_cleanup = True
        return self._httpx_client
