import ipaddress

from fastapi import APIRouter, HTTPException, Request

from app.core.providers import get_configured_api_key, save_runtime_api_key

router = APIRouter(prefix="/settings", tags=["settings"])


def _local_request(request: Request) -> bool:
    host = request.client.host if request.client else ""
    if host == "testclient":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@router.get("/llm")
async def llm_status():
    return {"configured": bool(get_configured_api_key()), "provider": "DashScope"}


@router.put("/llm/key")
async def configure_llm_key(request: Request):
    if not _local_request(request):
        raise HTTPException(status_code=403, detail="API key configuration is local-only")
    try:
        payload = await request.json()
        api_key = payload.get("api_key") if isinstance(payload, dict) else None
        if not isinstance(api_key, str):
            raise ValueError
        save_runtime_api_key(api_key)
    except (ValueError, UnicodeDecodeError) as error:
        raise HTTPException(status_code=422, detail="A valid DashScope API key is required") from error
    except OSError as error:
        raise HTTPException(status_code=500, detail="Failed to save API key locally") from error
    return {"configured": True, "provider": "DashScope"}
