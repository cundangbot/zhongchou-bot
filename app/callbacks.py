from __future__ import annotations

def cb_admin_list(list_type: str, page: int = 0) -> str:
    return f'admin:list:{list_type}:{max(0, int(page))}'

def parse_admin_list(data: str | None) -> tuple[str, int]:
    parts = (data or '').split(':')
    list_type = parts[2] if len(parts) > 2 else ''
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    return list_type, page

def cb_support_hold(ticket_id: int) -> str:
    return f'admin:support_hold:{int(ticket_id)}'

def cb_resource_finish(project_id: int) -> str:
    return f'resource:finish:{int(project_id)}'
