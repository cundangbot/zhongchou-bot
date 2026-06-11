from __future__ import annotations

"""Offline startup/import self-check.

Run from the project root after configuring .env:
    python scripts/check_startup_imports.py

The script never contacts Telegram. It verifies module imports, DB initialization,
router registration and scheduler job construction.
"""

import asyncio
import ast
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = ROOT / "app"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def find_top_level_import_cycles() -> list[list[str]]:
    modules: dict[str, Path] = {}
    for path in APP_ROOT.rglob("*.py"):
        module = path.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
        if module.endswith(".__init__"):
            module = module[: -len(".__init__")]
        modules[module] = path

    graph: dict[str, set[str]] = {name: set() for name in modules}
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in modules:
                        graph[name].add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in modules:
                    graph[name].add(node.module)
                for alias in node.names:
                    candidate = f"{node.module}.{alias.name}"
                    if candidate in modules:
                        graph[name].add(candidate)

    visited: set[str] = set()
    active: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []

    def visit(module: str) -> None:
        visited.add(module)
        active.add(module)
        stack.append(module)
        for dependency in graph[module]:
            if dependency not in visited:
                visit(dependency)
            elif dependency in active:
                index = stack.index(dependency)
                cycles.append(stack[index:] + [dependency])
        stack.pop()
        active.remove(module)

    for module in graph:
        if module not in visited:
            visit(module)
    return cycles


async def main() -> None:
    cycles = find_top_level_import_cycles()
    if cycles:
        raise RuntimeError(f"发现顶层循环导入：{cycles}")
    print("OK: 未发现顶层循环导入")

    import app.main  # noqa: F401
    print("OK: app.main 导入成功")

    from app.db.base import Base, init_db

    await init_db()
    print(f"OK: 数据库初始化成功，已注册 {len(Base.metadata.tables)} 张表")

    from aiogram import Dispatcher
    from aiogram.fsm.storage.memory import MemoryStorage
    from app.handlers import crowdfund, fallback, start

    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(start.router)
    dispatcher.include_router(crowdfund.router)
    dispatcher.include_router(fallback.router)
    print(f"OK: 路由注册成功，共 {len(dispatcher.sub_routers)} 个顶层路由")

    from app.scheduler import setup_scheduler

    class OfflineBot:
        pass

    scheduler = setup_scheduler(OfflineBot())
    print(f"OK: 调度任务构建成功，共 {len(scheduler.get_jobs())} 个任务")


if __name__ == "__main__":
    os.chdir(ROOT)
    asyncio.run(main())
