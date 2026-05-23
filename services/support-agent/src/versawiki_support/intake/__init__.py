"""Channel adapters: email, web, programmatic API."""

from .email import EmailPoller, FetchedEmail, ImapClient
from .web import build_web_app, WebMessageIn, WebMessageOut
from .api import build_api_app, ApiMessageIn, ApiMessageOut

__all__ = [
    "EmailPoller",
    "FetchedEmail",
    "ImapClient",
    "build_web_app",
    "WebMessageIn",
    "WebMessageOut",
    "build_api_app",
    "ApiMessageIn",
    "ApiMessageOut",
]
