import hmac
from fastapi import APIRouter, HTTPException, status
from app.auth import DEMO_IDENTITIES, issue_demo_token
from app.models import DemoIdentity, DemoLoginRequest, DemoLoginResponse

router = APIRouter(prefix="/api/demo", tags=["demo-auth"])

@router.get("/identities", response_model=list[DemoIdentity])
def list_demo_identities() -> list[DemoIdentity]:
    return list(DEMO_IDENTITIES.values())

@router.post("/login", response_model=DemoLoginResponse)
def demo_login(payload: DemoLoginRequest) -> DemoLoginResponse:
    identity = DEMO_IDENTITIES.get(payload.identity_id)
    if identity is None or not hmac.compare_digest(identity.demo_key, payload.demo_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid demo identity or key")
    return DemoLoginResponse(access_token=issue_demo_token(identity), expires_in=28_800, identity=identity)
