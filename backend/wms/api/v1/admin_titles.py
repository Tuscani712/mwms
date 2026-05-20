"""Admin Titles router (SCO-70).

Reads are open to all authed users (so dropdowns can populate);
writes require permission_level >= 3.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from wms.core.deps import get_current_user, get_session
from wms.models import User
from wms.schemas.titles import TitleCreate, TitleOut, TitleUpdate
from wms.services import titles as svc

router = APIRouter(prefix="/admin/titles", tags=["admin-titles"])


@router.get("", response_model=list[TitleOut])
def list_titles(
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[TitleOut]:
    # Only Lvl 3+ may see inactive titles (avoids leaking renamed/retired labels)
    if include_inactive and user.permission_level < svc.TITLES_WRITE_MIN_LEVEL:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "include_inactive requires permission_level >= 3",
        )
    return svc.list_titles(db, include_inactive=include_inactive)


@router.post("", response_model=TitleOut, status_code=status.HTTP_201_CREATED)
def create_title(
    payload: TitleCreate,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TitleOut:
    try:
        return svc.create_title(db, user, name=payload.name)
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except FileExistsError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.put("/{title_id}", response_model=TitleOut)
def update_title(
    title_id: int,
    payload: TitleUpdate,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TitleOut:
    try:
        return svc.update_title(
            db, user, title_id=title_id, name=payload.name, is_active=payload.is_active
        )
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except FileExistsError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.delete("/{title_id}", response_model=TitleOut)
def soft_delete_title(
    title_id: int,
    db: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TitleOut:
    try:
        return svc.soft_delete_title(db, user, title_id=title_id)
    except PermissionError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e
    except LookupError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
