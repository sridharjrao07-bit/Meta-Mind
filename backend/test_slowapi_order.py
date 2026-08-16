import asyncio
from fastapi import FastAPI, Depends, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

def get_user_id_or_ip(request: Request) -> str:
    print("Key func called! hasattr:", hasattr(request.state, "user_id"))
    if hasattr(request.state, "user_id"):
        return request.state.user_id
    return get_remote_address(request)

limiter = Limiter(key_func=get_user_id_or_ip)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

async def auth_dep(request: Request):
    print("Auth dep running!")
    request.state.user_id = "user123"
    return "user123"

@app.get("/test")
@limiter.limit("5/minute")
async def test_route(request: Request, user: str = Depends(auth_dep)):
    return {"user": user}

if __name__ == "__main__":
    from fastapi.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/test")
    print(resp.json())
