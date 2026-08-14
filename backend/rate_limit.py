from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

def get_user_id_or_ip(request: Request) -> str:
    """
    Returns the user_id if present on the request state (set by middleware),
    otherwise falls back to the client's IP address.
    """
    if hasattr(request.state, "user_id") and request.state.user_id:
        return request.state.user_id
    return get_remote_address(request)

limiter = Limiter(key_func=get_user_id_or_ip)
