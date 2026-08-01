from __future__ import annotations

import json
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import FinancialLedger


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))


async def post_ledger(
    session: AsyncSession,
    *,
    idempotency_key: str,
    direction: str,
    category: str,
    amount,
    payment_source: str = 'real',
    project_id: int | None = None,
    order_id: int | None = None,
    refund_id: int | None = None,
    payout_id: int | None = None,
    user_id: int | None = None,
    operator_id: int | None = None,
    description: str | None = None,
    metadata: dict | None = None,
) -> FinancialLedger:
    """Append an immutable, idempotent financial ledger entry."""
    values = dict(
        idempotency_key=idempotency_key,
        direction=direction,
        category=category,
        amount=money(amount),
        payment_source=payment_source,
        project_id=project_id,
        order_id=order_id,
        refund_id=refund_id,
        payout_id=payout_id,
        user_id=user_id,
        operator_id=operator_id,
        description=description,
        metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
    )
    stmt = (
        pg_insert(FinancialLedger)
        .values(**values)
        .on_conflict_do_nothing(index_elements=['idempotency_key'])
        .returning(FinancialLedger.id)
    )
    inserted_id = (await session.execute(stmt)).scalar_one_or_none()
    if inserted_id is not None:
        return (await session.execute(
            select(FinancialLedger).where(FinancialLedger.id == inserted_id)
        )).scalar_one()
    return (await session.execute(
        select(FinancialLedger).where(FinancialLedger.idempotency_key == idempotency_key)
    )).scalar_one()
