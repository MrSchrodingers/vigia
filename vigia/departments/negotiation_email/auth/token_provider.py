# vigia/departments/negotiation_email/auth/token_provider.py
import time
import requests
import structlog
from typing import Optional, Dict
from vigia.config import settings

logger = structlog.get_logger(__name__)

class TokenProvider:
    _token_cache: Dict[str, Dict] = {}
    DEFAULT_SCOPE = "https://graph.microsoft.com/.default"

    def get_token(self, scope: Optional[str] = None) -> str:
        target_scope = scope or self.DEFAULT_SCOPE
        
        cached_token = self._token_cache.get(target_scope)
        if cached_token and time.time() < cached_token.get("expires_at", 0):
            return cached_token["access_token"]

        logger.info("token_provider.get_token.acquiring_new", scope=target_scope)
        url = f"https://login.microsoftonline.com/{settings.TENANT_ID}/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": settings.CLIENT_ID,
            "client_secret": settings.CLIENT_SECRET,
            "scope": target_scope,
        }
        
        resp = requests.post(url, data=data)
        resp.raise_for_status()
        token_data = resp.json()

        expires_at = time.time() + int(token_data.get("expires_in", 3599)) - 60
        self._token_cache[target_scope] = {
            "access_token": token_data["access_token"],
            "expires_at": expires_at,
        }
        return token_data["access_token"]

TOKEN_PROVIDER = TokenProvider()