import secrets
import os
from typing import Union

from fastapi.security import HTTPBasic
from fastapi import Request, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles


async def verify_username(request: Request, security=Depends(HTTPBasic)) -> str:
    """Verify username and password from HTTP Basic Auth."""
    credentials = await security(request)

    correct_username = secrets.compare_digest(
        credentials.username, os.getenv("USERNAME", "admin")
    )
    correct_password = secrets.compare_digest(
        credentials.password, os.getenv("PASSWORD", "admin@123")
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


class AuthStaticFiles(StaticFiles):
    def __init__(
        self, directory: Union[str, "os.PathLike[str]"], *args, **kwargs
    ) -> None:
        """Initialize with directory and pass other args to parent."""
        super().__init__(directory=directory, *args, **kwargs)

    async def __call__(self, scope, receive, send) -> None:
        """Handle authentication before serving static files."""
        assert scope["type"] == "http"

        request = Request(scope, receive)

        try:
            # Try to authenticate
            await verify_username(request)
            # If authentication succeeds, serve the static file
            await super().__call__(scope, receive, send)
        except HTTPException as exc:
            # If authentication fails, send a proper 401 response
            if exc.status_code == status.HTTP_401_UNAUTHORIZED:
                headers = [
                    (b"content-type", b"text/plain"),
                    (b"www-authenticate", b'Basic realm="Authentication Required"'),
                ]
                await send(
                    {"type": "http.response.start", "status": 401, "headers": headers}
                )
                await send(
                    {"type": "http.response.body", "body": b"Authentication required"}
                )
            else:
                # For other exceptions, re-raise
                raise
