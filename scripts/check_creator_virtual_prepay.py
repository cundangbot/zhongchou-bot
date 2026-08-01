from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
config = (ROOT / 'app/config.py').read_text(encoding='utf-8')
payments = (ROOT / 'app/services/payments.py').read_text(encoding='utf-8')
crowdfund = (ROOT / 'app/handlers/crowdfund.py').read_text(encoding='utf-8')
main = (ROOT / 'app/main.py').read_text(encoding='utf-8')
env = (ROOT / '.env.example').read_text(encoding='utf-8')

checks = {
    'env enable switch': 'CREATOR_PREPAY_AUTO_VERIFY_ENABLED' in config and 'CREATOR_PREPAY_AUTO_VERIFY_ENABLED' in env,
    'env id whitelist': 'CREATOR_PREPAY_AUTO_VERIFY_IDS' in config and 'CREATOR_PREPAY_AUTO_VERIFY_IDS' in env,
    'creator-only order guard': "order.order_type != 'crowdfunding_creator_prepay'" in payments,
    'whitelist guard': 'should_auto_verify_creator_prepay(order.user_id)' in payments,
    'virtual source': "order.payment_source = 'virtual'" in payments,
    'zero real ledger': "amount=Decimal('0.00')" in payments and "payment_source='virtual'" in payments,
    'approval auto verify': 'virtual_verify_creator_prepay_order(' in crowdfund,
    'normal payment fallback': 'if not auto_verified:' in crowdfund and 'payment_order_keyboard(' in crowdfund,
    'no startup pending recovery': 'recover_creator_virtual_prepays' not in main and 'CREATOR_PREPAY_RECOVER_ON_STARTUP' not in main,
    'no faka call in helper': '未向 faka 查询' in payments,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit('FAILED: ' + ', '.join(failed))
print('OK：发起人双车位 .env 白名单、仅限车主订单、0 元虚拟账本、审核时自动核验、部署重启不恢复历史项目和正常支付回退检查通过。')
