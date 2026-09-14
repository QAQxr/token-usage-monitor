# TokenWatch

这是一个只面向 Ubuntu 22.04 + Codex GUI 的本地只读 TokenWatch MVP。

它不会修改 Codex、`auth.json` 或 `~/.codex/sessions`，也不会联网。Codex 和 TokenWatch 可以分别启动；TokenWatch 只在同时发现 Codex GUI、loopback CDP 和当前 rollout 时显示窗口。

## 当前实现

- `127.0.0.1:9222/json/list` 发现 `app://-/index.html` 主 renderer。
- 通过 location、history state 和活动 DOM 候选读取当前 thread UUID；候选不唯一时不猜。
- 通过 rollout 文件名和 `session_meta` UUID 映射到 `~/.codex/sessions/**/*.jsonl`；同一 thread 的多份 rollout 使用最新一份。
- 第一次绑定全量读取，之后只读取 JSONL 新增字节；文件替换或 truncate 会安全重建。
- `REQ` 定义为当前 rollout 中有效 `token_count` usage snapshot 数量。
- GTK3 纯文字窗口，内容固定 12 行；正常态只替换数字和进度条。
- X11 下首次显示时默认贴在 Codex 右侧；之后不再因 Codex 移动、缩放或最大化重新定位，用户拖到哪里就保持在哪里；窗口默认全局置顶，但只设置一次；最小化时隐藏。

## 启动

先直接运行一次探针：

```bash
cd ~/codex/projects/token-usage-monitor
python3 -m tokenwatch --probe
```

启动 TokenWatch 窗口：

```bash
python3 -m tokenwatch --companion
```

也可以从应用菜单启动 `TokenWatch`，不需要打开终端。项目内的
`scripts/tokenwatch.desktop` 是对应的用户级启动器；它不会修改系统级
桌面文件。TokenWatch 带有用户级单实例锁，重复点击不会创建多个窗口。

TokenWatch 也可以由用户级 systemd 服务在登录后自动启动：

```bash
systemctl --user status tokenwatch.service
journalctl --user -u tokenwatch.service -f
```

`--gui` 仍作为同义入口保留：

```bash
python3 -m tokenwatch --gui
```

当 Codex 没有用 `--remote-debugging-address=127.0.0.1 --remote-debugging-port=9222` 启动时，窗口会保持隐藏。

如果要让应用菜单里的 Codex 默认带上这些参数，可安装项目里的用户级启动包装器：

```bash
install -Dm755 scripts/chatgpt-tokenwatch ~/.local/bin/chatgpt-tokenwatch
sed -i 's#^Exec=/home/o_o/.local/bin/chatgpt-proxy %U#Exec=/home/o_o/.local/bin/chatgpt-tokenwatch %U#' ~/.local/share/applications/chatgpt.desktop
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

安装后完全退出并重新打开 Codex；TokenWatch 服务会在后台等待并自动连接。

## 离线验证

按 thread UUID 渲染某个真实 rollout：

```bash
python3 -m tokenwatch --render-thread THREAD_UUID
```

运行完整测试：

```bash
python3 -m unittest discover -s tests -v
```

测试包含 A→B→C→A 的精确映射、歧义拒绝、增量读取和固定布局检查。真实 GUI A→B→C→A 验收需要 Codex 实例实际暴露 9222；当前 MVP 不会把 CDP 不可用误判成某个 rollout。

## 固定 UI

```text
╭──────────────────────────────╮
│ ▼ TokenWatch      94.70% HIT │
├──────────────────────────────┤
│ 3.89M   12     3.83M     60K │
│ TOTAL   REQ    INPUT     OUT │
│                              │
│ Session ██████████████ 91.90%│
│ Last    ██████████████ 94.70%│
│                              │
│ Context █████░░░░░░░░  33.40%│
│                86.2K / 258K│
│                              │
│ 5h 10.00%          7d  4.00% │
╰──────────────────────────────╯
```
