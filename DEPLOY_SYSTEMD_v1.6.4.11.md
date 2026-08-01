# v1.6.4.11 systemd 覆盖部署

压缩包为扁平结构，根目录直接包含 `app/`、`VERSION` 和 `requirements.txt`。

```bash
cd /opt
sudo systemctl stop zhongchou_bot
sudo rm -rf /tmp/zhongchou_bot_release
sudo mkdir -p /tmp/zhongchou_bot_release
sudo unzip -o /path/new_code_v1.6.4.11_member_menu_no_history_scan.zip -d /tmp/zhongchou_bot_release
cat /tmp/zhongchou_bot_release/VERSION
sudo rsync -a --delete \
  --exclude='.env' \
  --exclude='venv/' \
  --exclude='backups/' \
  /tmp/zhongchou_bot_release/ /opt/zhongchou_bot/
sudo systemctl start zhongchou_bot
sudo journalctl -u zhongchou_bot -n 100 --no-pager
```

机器人重新打开 `/start` 后，底部菜单应为：发起众筹、热门众筹、会员购买、我的众筹。

部署/重启不会扫描或修改任何历史拼车项目及频道模板。
