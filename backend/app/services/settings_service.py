"""Application settings with an append-only audit trail.

The evidence threshold decides whether a relationship may enter review, so its
version, effective time, author and reason are part of the contract. Reading and
writing settings must therefore go through here, never through raw UPDATE.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.models.ops import AppSetting, AppSettingHistory
from app.validation.state_guard import EvidenceThreshold

THRESHOLD_KEYS = (
    "evidence.threshold_version",
    "evidence.required_grades",
    "evidence.min_c_origins",
    "evidence.auto_verify",
)


async def get_setting(session: AsyncSession, key: str) -> dict | None:
    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == key))
    ).scalar_one_or_none()
    return row.value if row else None


async def set_setting(
    session: AsyncSession,
    key: str,
    value: dict | list | str | int | bool,
    *,
    actor: str,
    reason: str,
) -> AppSetting:
    """Upsert a setting, bump its version and append an audit row."""
    if not reason.strip():
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            "Changing a setting requires a reason",
            details={"key": key},
        )

    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == key))
    ).scalar_one_or_none()

    payload = {"v": value} if not isinstance(value, dict) else value

    if row is None:
        row = AppSetting(key=key, value=payload, version=1, updated_by=actor)
        session.add(row)
        session.add(
            AppSettingHistory(
                key=key,
                old_value=None,
                new_value=payload,
                old_version=None,
                new_version=1,
                reason=reason,
                actor=actor,
            )
        )
    else:
        old_value = row.value
        old_version = row.version
        row.value = payload
        row.version = old_version + 1
        row.updated_by = actor
        session.add(
            AppSettingHistory(
                key=key,
                old_value=old_value,
                new_value=payload,
                old_version=old_version,
                new_version=row.version,
                reason=reason,
                actor=actor,
            )
        )

    await session.flush()
    return row


async def get_threshold(session: AsyncSession) -> EvidenceThreshold:
    """Build the threshold from persisted settings, falling back to defaults."""
    from app.schemas.enums import EvidenceGrade

    version = await get_setting(session, "evidence.threshold_version")
    grades = await get_setting(session, "evidence.required_grades")
    min_c = await get_setting(session, "evidence.min_c_origins")
    auto = await get_setting(session, "evidence.auto_verify")

    def _unwrap(value: object, fallback: object) -> object:
        if value is None:
            return fallback
        if isinstance(value, dict) and "v" in value:
            return value["v"]
        return value

    raw_grades = _unwrap(grades, ["A", "B"])
    if not isinstance(raw_grades, list):
        raw_grades = ["A", "B"]

    return EvidenceThreshold(
        version=str(_unwrap(version, "v1")),
        required_grades=frozenset(EvidenceGrade(g) for g in raw_grades),
        min_c_origins=int(_unwrap(min_c, 2)),  # type: ignore[arg-type]
        # Even if someone flips this to true, evaluate_verification still demands
        # an explicit approval; the flag is recorded but cannot bypass the guard.
        auto_verify=bool(_unwrap(auto, False)),
    )


__all__ = ["THRESHOLD_KEYS", "get_setting", "get_threshold", "set_setting"]
