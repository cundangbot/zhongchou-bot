from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PaymentProductSpec:
    kind: str
    canonical_name: str
    display_name: str
    amount: Decimal
    seat_price: Decimal
    creator_prepay: bool


PRODUCT_SPECS: tuple[PaymentProductSpec, ...] = (
    PaymentProductSpec(
        kind='seat_30',
        canonical_name='车位支付链接[拼车单车位30元支付链接]',
        display_name='拼车单车位30元',
        amount=Decimal('30.00'),
        seat_price=Decimal('30.00'),
        creator_prepay=False,
    ),
    PaymentProductSpec(
        kind='seat_60',
        canonical_name='车位支付链接[拼车单车位60元支付链接]',
        display_name='拼车单车位60元',
        amount=Decimal('60.00'),
        seat_price=Decimal('60.00'),
        creator_prepay=False,
    ),
    PaymentProductSpec(
        kind='creator_60',
        canonical_name='车位支付链接[发起人双车位60元支付链接]',
        display_name='发起人双车位60元',
        amount=Decimal('60.00'),
        seat_price=Decimal('30.00'),
        creator_prepay=True,
    ),
    PaymentProductSpec(
        kind='creator_120',
        canonical_name='车位支付链接[发起人双车位120元支付链接]',
        display_name='发起人双车位120元',
        amount=Decimal('120.00'),
        seat_price=Decimal('60.00'),
        creator_prepay=True,
    ),
)

_BY_CANONICAL = {
    re.sub(r'[\s\u200b\u200c\u200d\ufeff]+', '', spec.canonical_name).casefold(): spec
    for spec in PRODUCT_SPECS
}
_BY_KIND = {spec.kind: spec for spec in PRODUCT_SPECS}


def canonical_product_name(value: str | None) -> str:
    return re.sub(r'[\s\u200b\u200c\u200d\ufeff]+', '', value or '').casefold()


def detect_payment_product(value: str | None) -> PaymentProductSpec | None:
    """Recognize only the four configured carpool payment products.

    Whitespace inside the product name is ignored, but other products are not
    accepted by prefix/substring alone. This prevents unrelated shop purchases
    from triggering a VP query.
    """
    return _BY_CANONICAL.get(canonical_product_name(value))


def payment_product_by_kind(kind: str | None) -> PaymentProductSpec | None:
    return _BY_KIND.get((kind or '').strip())


def ticket_type_label(order_type: str | None) -> tuple[str, str]:
    if order_type == 'crowdfunding_creator_prepay':
        return '👑', '发起人双车位'
    if order_type == 'crowdfunding_after_full':
        return '🔓', '满员后补票'
    return '🚗', '普通车位'
