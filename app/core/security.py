from dataclasses import dataclass
from typing import Annotated

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import AppError


@dataclass(frozen=True)
class Principal:
    subject: str


service_bearer = HTTPBearer(auto_error=False)


def get_current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(service_bearer)] = None,
) -> Principal:
    settings = request.app.state.settings
    if settings.security.disable_auth:
        return Principal(subject="dev")
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or credentials.credentials != settings.security.service_api_key_value
    ):
        raise AppError("UNAUTHORIZED")
    return Principal(subject="service")
