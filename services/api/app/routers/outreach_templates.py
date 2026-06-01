from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from jinja2 import TemplateSyntaxError
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.db.session import get_db
from app.outreach_templates import (
    get_template,
    list_templates,
    placeholder_help,
    render_stored_template,
    render_template_text,
    sample_render_context,
    validate_slug,
)
from app.schemas import (
    OutreachTemplateMeta,
    OutreachTemplatePreview,
    OutreachTemplateRead,
    OutreachTemplateUpdate,
)

router = APIRouter(prefix="/outreach-templates", tags=["outreach-templates"])


@router.get("/meta", response_model=OutreachTemplateMeta)
def outreach_template_meta() -> OutreachTemplateMeta:
    return OutreachTemplateMeta(placeholders=placeholder_help())


@router.get("", response_model=list[OutreachTemplateRead])
def list_outreach_templates(db: Session = Depends(get_db)) -> list[OutreachTemplateRead]:
    rows = list_templates(db)
    return [OutreachTemplateRead.model_validate(r) for r in rows]


@router.get("/{slug}", response_model=OutreachTemplateRead)
def get_outreach_template(slug: str, db: Session = Depends(get_db)) -> OutreachTemplateRead:
    try:
        validate_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    row = get_template(db, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="template not found")
    return OutreachTemplateRead.model_validate(row)


@router.put("/{slug}", response_model=OutreachTemplateRead)
def update_outreach_template(
    slug: str,
    body: OutreachTemplateUpdate,
    db: Session = Depends(get_db),
) -> OutreachTemplateRead:
    try:
        validate_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    row = get_template(db, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="template not found")
    try:
        render_template_text(body.body, subject=body.subject)
    except TemplateSyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"template syntax error: {exc}") from exc
    row.body = body.body
    row.subject = body.subject
    row.updated_by = body.updated_by
    row.updated_at = datetime.now(tz=UTC)
    db.add(row)
    db.commit()
    db.refresh(row)
    write_audit(
        db,
        actor=body.updated_by,
        action="outreach_template_updated",
        entity_type="outreach_template",
        entity_id=slug,
        meta={"channel": row.channel},
    )
    return OutreachTemplateRead.model_validate(row)


@router.post("/{slug}/preview", response_model=OutreachTemplatePreview)
def preview_outreach_template(
    slug: str,
    db: Session = Depends(get_db),
) -> OutreachTemplatePreview:
    try:
        validate_slug(slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    row = get_template(db, slug)
    if row is None:
        raise HTTPException(status_code=404, detail="template not found")
    ctx = sample_render_context()
    try:
        rendered_body, rendered_subject = render_stored_template(row, context=ctx)
    except TemplateSyntaxError as exc:
        raise HTTPException(status_code=400, detail=f"template syntax error: {exc}") from exc
    return OutreachTemplatePreview(
        slug=slug,
        subject=rendered_subject,
        body=rendered_body,
        sample_context=ctx,
    )
