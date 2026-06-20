"""Prompt library (F2): a personal collection + a seeded community catalog.

A prompt is reusable text a user can drop into the composer to start a message.
Community prompts (``user_email is None``) are read-only; importing one creates an
editable personal copy that records its ``source_id``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from studioapi.db import SessionLocal
from studioapi.deps import current_user, require_service
from studioapi.models import Prompt, User

router = APIRouter(prefix="/prompts", tags=["Prompts"], dependencies=[Depends(require_service)])


# --- seeded community catalog (user_email = None; fixed ids for idempotency) ---
COMMUNITY: list[dict] = [
    {
        "id": "cpr_earnings", "title": "실적 요약", "category": "리서치",
        "description": "한 종목의 최근 분기 실적을 핵심 지표 중심으로 정리.",
        "body": "{TICKER}의 가장 최근 분기 실적을 매출·영업이익·순이익·EPS 중심으로 요약하고, "
                "전년 동기 대비 증감과 함께 각 수치의 출처(공시)를 표시해줘.",
    },
    {
        "id": "cpr_filings_risk", "title": "리스크 공시 점검", "category": "리서치",
        "description": "최근 공시에서 드러난 사업·공급망 리스크를 출처와 함께 정리.",
        "body": "{TICKER}의 최근 공시(10-K/사업보고서)에서 언급된 주요 사업·공급망·규제 리스크를 "
                "항목별로 정리하고, 각 항목을 해당 공시 문구에 근거해 출처와 함께 보여줘.",
    },
    {
        "id": "cpr_macro_rates", "title": "금리·물가 점검", "category": "거시",
        "description": "미국/한국의 최근 정책금리와 물가 지표를 as-of 날짜와 함께.",
        "body": "미국(FRED)과 한국(ECOS)의 최근 기준금리와 소비자물가 지표를 각각 가져와서, "
                "각 수치의 기준일(as-of)과 함께 한 줄씩 정리해줘. 예측은 하지 말고 사실만.",
    },
    {
        "id": "cpr_holdings_news", "title": "보유 종목 뉴스 브리핑", "category": "뉴스",
        "description": "관심 종목들의 최근 뉴스를 출처 링크와 함께 묶어서.",
        "body": "{TICKERS} 각 종목의 최근 주요 뉴스를 2~3개씩 골라 한 줄 요약과 출처 링크를 붙여줘. "
                "점수·전망·매수의견은 넣지 말고 사실 위주로.",
    },
    {
        "id": "cpr_price_trend", "title": "가격 흐름 설명", "category": "시황",
        "description": "최근 가격 흐름을 사실 기반으로 설명(예측 없음).",
        "body": "{TICKER}의 최근 가격 흐름(시작가/종가/등락)을 사실 기반으로 설명해줘. "
                "앞으로의 방향이나 목표가는 절대 제시하지 말고, 무엇이 있었는지만.",
    },
]


def seed_community_prompts() -> None:
    with SessionLocal() as db:
        for c in COMMUNITY:
            if db.get(Prompt, c["id"]):
                continue
            db.add(Prompt(
                id=c["id"], user_email=None, title=c["title"], description=c.get("description"),
                body=c["body"], category=c.get("category"), community=True,
            ))
        db.commit()


# --- schemas --------------------------------------------------------------
class PromptIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    description: str | None = None
    category: str | None = None


class PromptPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    description: str | None = None
    category: str | None = None


def _out(p: Prompt) -> dict:
    return {
        "id": p.id, "title": p.title, "description": p.description, "body": p.body,
        "category": p.category, "community": p.community, "source_id": p.source_id,
        "editable": p.user_email is not None,
    }


# --- endpoints ------------------------------------------------------------
@router.get("", summary="The user's personal prompt library")
async def list_prompts(user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        rows = db.execute(
            select(Prompt).where(Prompt.user_email == user.email).order_by(Prompt.created_at.desc())
        ).scalars().all()
        return {"prompts": [_out(p) for p in rows]}


@router.get("/community", summary="The seeded community catalog (read-only)")
async def list_community(user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        rows = db.execute(
            select(Prompt).where(Prompt.user_email.is_(None)).order_by(Prompt.category, Prompt.title)
        ).scalars().all()
        return {"prompts": [_out(p) for p in rows]}


@router.post("", summary="Create a personal prompt")
async def create_prompt(body: PromptIn, user: User = Depends(current_user)) -> dict:
    p = Prompt(
        user_email=user.email, title=body.title, description=body.description,
        body=body.body, category=body.category, community=False,
    )
    with SessionLocal() as db:
        db.add(p)
        db.commit()
        return _out(p)


@router.post("/{prompt_id}/import", summary="Import a community prompt into the user's library")
async def import_prompt(prompt_id: str, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        src = db.get(Prompt, prompt_id)
        if src is None or src.user_email is not None:
            raise HTTPException(404, "Community prompt not found.")
        # idempotent: if already imported, return the existing copy
        existing = db.execute(
            select(Prompt).where(Prompt.user_email == user.email, Prompt.source_id == src.id)
        ).scalars().first()
        if existing:
            return _out(existing)
        copy = Prompt(
            user_email=user.email, title=src.title, description=src.description, body=src.body,
            category=src.category, community=False, source_id=src.id,
        )
        db.add(copy)
        db.commit()
        return _out(copy)


@router.get("/{prompt_id}", summary="Get one prompt (own or community)")
async def get_prompt(prompt_id: str, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        p = db.get(Prompt, prompt_id)
        if p is None or (p.user_email is not None and p.user_email != user.email):
            raise HTTPException(404, "Prompt not found.")
        return _out(p)


@router.patch("/{prompt_id}", summary="Update a personal prompt (own only)")
async def update_prompt(prompt_id: str, body: PromptPatch, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        p = db.get(Prompt, prompt_id)
        if p is None or p.user_email != user.email:
            raise HTTPException(404, "Prompt not found or not editable.")
        if body.title is not None:
            p.title = body.title
        if body.body is not None:
            p.body = body.body
        if body.description is not None:
            p.description = body.description
        if body.category is not None:
            p.category = body.category
        db.commit()
        return _out(p)


@router.delete("/{prompt_id}", summary="Delete a personal prompt (own only)")
async def delete_prompt(prompt_id: str, user: User = Depends(current_user)) -> dict:
    with SessionLocal() as db:
        p = db.get(Prompt, prompt_id)
        if p is None or p.user_email != user.email:
            raise HTTPException(404, "Prompt not found or not deletable.")
        db.delete(p)
        db.commit()
        return {"deleted": prompt_id}
