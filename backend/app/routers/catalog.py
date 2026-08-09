from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.db import get_db
from app.models import Tag, User, VisitType
from app.schemas.catalog import TagCreate, TagOut, VisitTypeCreate, VisitTypeOut

router = APIRouter(tags=["catalog"])


# ---- Visit types (shared catalog) ----
@router.get("/visit_types", response_model=list[VisitTypeOut])
def list_visit_types(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(VisitType).order_by(VisitType.label)).all()


@router.post("/visit_types", response_model=VisitTypeOut, status_code=status.HTTP_201_CREATED)
def create_visit_type(
    payload: VisitTypeCreate,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if db.scalar(select(VisitType).where(VisitType.key == payload.key)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Visit type key exists")
    vt = VisitType(key=payload.key, label=payload.label)
    db.add(vt)
    db.commit()
    db.refresh(vt)
    return vt


# ---- Tags (per-user) ----
@router.get("/tags", response_model=list[TagOut])
def list_tags(current: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Tag).where(Tag.owner_id == current.id).order_by(Tag.name)).all()


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(
    payload: TagCreate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.scalar(select(Tag).where(Tag.owner_id == current.id, Tag.name == payload.name))
    if existing:
        return existing
    tag = Tag(owner_id=current.id, name=payload.name)
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: int,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tag = db.get(Tag, tag_id)
    if tag is None or tag.owner_id != current.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    db.delete(tag)
    db.commit()
