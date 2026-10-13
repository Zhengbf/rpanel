import sqlalchemy
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from app.api.deps import get_db, get_current_user, get_router_client, DbSession
from app.db.models import DeviceNote, AuditLog
from app.services.devices import DeviceService

router = APIRouter(prefix="/api/devices", tags=["devices"])


class NoteRequest(BaseModel):
    ip: str
    mac: str | None = None
    note: str = ""


@router.get("", response_model=None)
async def list_devices(
    user: dict = Depends(get_current_user),
    client=Depends(get_router_client),
    db: DbSession = None,
):
    svc = DeviceService(client)
    devices = await svc.list_devices()
    notes = (await db.execute(select(DeviceNote))).scalars().all()
    note_map = {n.ip: n.note for n in notes}
    for d in devices:
            d.note = note_map.get(d.ip, "") or (d.comment if hasattr(d, "comment") else "")
    return [d.model_dump() for d in devices]


@router.put("/note", response_model=None)
async def set_note(
    body: NoteRequest,
    user: dict = Depends(get_current_user),
    db: DbSession = None,
):
    existing = await db.get(DeviceNote, body.ip)
    if existing:
        existing.note = body.note
        existing.mac = body.mac or existing.mac
    else:
        db.add(DeviceNote(ip=body.ip, mac=body.mac, note=body.note))
    db.add(AuditLog(user_id=user["user_id"], username=user["username"],
                    action="set_note", target=body.ip, detail=body.note))
    await db.commit()
    return {"ok": True}

