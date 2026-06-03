# 自发众筹机器人 v1.4.7 云端部署版

本版本用于云端部署，保留自发众筹主流程：发起众筹、审核发车、用户上车支付、资源上传审核、资源领取、报销/退款/分润提现、管理员统计面板与风控记录。

## 主要入口

用户底部菜单：

```text
🚗 发起众筹   🔥 热门众筹
📋 我的众筹
```

Telegram `/` 命令菜单：

```text
/start
```

管理员额外可用：

```text
/admin_dashboard
/ban 用户ID 原因
/unban 用户ID
```

## 云端启动

```bash
pip install -r requirements.txt
python -m app.tools_login_telethon
python -m app.main
```

使用 Docker：

```bash
docker compose up -d --build
docker compose logs -f
```

## 重要配置

请复制 `.env.example` 为 `.env` 并填写真实配置：

```env
BOT_TOKEN=
ADMIN_GROUP_ID=
PUBLIC_CHANNEL_ID=
ADMIN_IDS=

PAYMENT_MODE=telethon
FAKA_BOT_USERNAME=
EXPECTED_FAKA_ORDER_BOT=@jingpinhybot
TELEGRAM_API_ID=
TELEGRAM_API_HASH=

SEAT_PRICE=30
NORMAL_PAYMENT_LINK=https://你的30元支付链接
CREATOR_PAYMENT_LINK=https://你的60元支付链接
PAYMENT_TEST_MODE=false
```

生产环境请保持：

```env
PAYMENT_TEST_MODE=false
```

## 部署前检查

1. 机器人已加入管理审核群，并有读取/发送消息权限。
2. 机器人已加入公开频道，并有发布和编辑消息权限。
3. 管理员 ID 已写入 `ADMIN_IDS`。
4. 发卡查询账号已完成 Telethon 登录。
5. 支付链接已替换为真实 30 元和 60 元链接。
6. 云端网络能访问 Telegram；如不能直连，请配置代理。

## 常用命令

启动：

```bash
python -m app.main
```

登录发卡查询账号：

```bash
python -m app.tools_login_telethon
```

查看 Docker 日志：

```bash
docker compose logs -f
```

## 数据库说明

默认使用 SQLite：

```env
DATABASE_URL=sqlite+aiosqlite:///./data/bot.db
```

云端部署前请确保存在 `data` 目录：

```bash
mkdir -p data
```

