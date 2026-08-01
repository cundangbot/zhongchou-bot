from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'


def fail(message: str) -> None:
    raise SystemExit(f'FAIL: {message}')


files = list(APP.rglob('*.py'))
texts = {path: path.read_text(encoding='utf-8') for path in files}
all_text = '\n'.join(texts.values())

# 1. Every generated callback must have a literal/prefix handler.
handlers: list[tuple[str, str]] = []
for text in texts.values():
    handlers.extend(('eq', match.group(2)) for match in re.finditer(r"F\.data\s*==\s*(['\"])(.*?)\1", text))
    handlers.extend(('prefix', match.group(2)) for match in re.finditer(r"F\.data\.startswith\((['\"])(.*?)\1\)", text))

unmatched: list[str] = []
for path, text in texts.items():
    for match in re.finditer(r"callback_data\s*=\s*f?(['\"])(.*?)\1", text):
        value = match.group(2)
        if value.startswith('{'):
            continue
        prefix = value.split('{', 1)[0]
        matched = any(
            (kind == 'eq' and '{' not in value and handler == value)
            or (kind == 'prefix' and (prefix.startswith(handler) or value.startswith(handler)))
            for kind, handler in handlers
        )
        if not matched:
            unmatched.append(f'{path.relative_to(ROOT)}: {value}')
if unmatched:
    fail('存在没有处理器的按钮：\n' + '\n'.join(unmatched))

# 2. No duplicate top-level names remain.
for path, text in texts.items():
    tree = ast.parse(text, filename=str(path))
    names: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] = names.get(node.name, 0) + 1
    duplicates = [name for name, count in names.items() if count > 1]
    if duplicates:
        fail(f'{path.relative_to(ROOT)} 存在重复顶层定义：{duplicates}')

# 3. Public flow closure markers.
required = {
    '发车流程取消': "callback_data='cf:cancel'",
    '购买资料取消': 'creator:buyinfo_cancel:',
    '资源上传取消': 'resource:cancel:',
    '提现/报销资料取消': 'creator:payout_cancel:',
    '退款资料取消': "F.data == 'refund:apply_cancel'",
    '用户结束客服': "F.data == 'support:end'",
    '管理员搜索取消': "F.data == 'admin:search_cancel'",
    '管理员客服回复取消': 'admin:support_reply_cancel:',
    '管理员补单取消': 'admin:manual_verify_cancel:',
    '资源领取返回详情': '🔙 返回资源详情',
    '热门项目返回列表': '⬅️ 返回热门众筹',
    '支付选择返回中心': '📋 返回我的众筹',
    '用户资源审核锁': 'CREATOR_RESOURCE_EDIT_LOCKED_STATES',
    '管理员资源编辑边界': 'ADMIN_RESOURCE_EDIT_LOCKED_STATES',
}
for label, marker in required.items():
    if marker not in all_text:
        fail(f'缺少闭环标记：{label} ({marker})')

# 4. Removed old public routes and wording.
forbidden = {
    "F.data == 'orders:pending'": '旧待付逐条入口',
    "F.data == 'orders:completed'": '旧已完成入口',
    "F.data == 'orders:participated'": '旧已上车逐条入口',
    "F.data == 'orders:created'": '旧车主逐条入口',
    '💬 在众筹机器人里联系小掌柜': '旧客服按钮文案',
}
for marker, label in forbidden.items():
    if marker in all_text:
        fail(f'仍存在{label}：{marker}')

# 5. Resource review permissions: creator locked, admin editable until publish/delivery.
crowdfund = texts[APP / 'handlers' / 'crowdfund.py']
keyboards = texts[APP / 'keyboards.py']
for marker in (
    "'resource_submitted', 'resource_review', 'resource_published', 'delivered'",
    "ADMIN_RESOURCE_EDIT_LOCKED_STATES = {'resource_published', 'delivered'}",
    '资源已经提交审核，当前不能继续上传、补充或清空',
    '普通用户已锁定；管理员仍可追加、删除、清空或重传',
    "text='📦 查看/修改资源'",
    "text='➕ 上传/补充资源'",
    "text='🗑 删除最新一条资源'",
    "text='🧹 清空全部资源'",
):
    if marker not in crowdfund and marker not in keyboards:
        fail(f'资源审核权限边界不完整：{marker}')

# 6. Ledger must support date paging and return path.
start = texts[APP / 'handlers' / 'start.py']
for marker in (
    '_beijing_day_bounds_utc_naive',
    'admin:list:ledger:{ledger_day_offset+1}:0',
    'admin:list:ledger:{ledger_day_offset-1}:0',
    "text='📅 回到今天'",
    "text='🏠 返回管理面板'",
):
    if marker not in start:
        fail(f'资金账本日期分页不完整：{marker}')

print('OK：按钮处理器、输入状态退出、用户资源锁、管理员资源编辑、按日资金账本、旧入口清理和主要返回路径检查通过。')
