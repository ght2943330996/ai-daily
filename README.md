# 钉钉 AI 日报机器人

每天早上 8 点，把以下内容推送到你的手机钉钉（**两条消息**）：

1. **📰 AI日报**：把 [大黑AI速报](https://news.daheiai.com/index.php)（每 4 小时更新一期的 AI 新闻快讯站）**昨天**的新闻汇总
2. **🔧 工具速报**：把 [大黑AI工具速报](https://news.daheiai.com/changelog.php)（AI 编程工具版本更新追踪）中 **Claude Code 和 Codex** 两个工具各自的最新 **5 条**版本更新

AI 日报：
- 按分类分组（模型动态 / 产品工具 / 技巧教程 / 硬件动态 / 行业资讯）
- 每条快讯 = 标题 + 一两句摘要 + **角标来源链接**（`[1](url)`，点击直达原帖）
- 附每期链接和网站入口，感兴趣可点击深入查看

工具速报：
- 只关注 **Claude Code** 和 **Codex** 两个工具（在 `send_ai_daily.py` 顶部 `TRACKED_TOOLS` / `TOOLS_PER_COUNT` 可改）
- 每个工具列最新 5 条更新：版本号 + 主要变更条目（最多 6 条，每条截断 80 字）
- **只推正式版**（`STABLE_ONLY = True`），nightly / alpha / beta 等预发布版本一律过滤
- 排除非主线分支（如 Codex 的 rusty-v8 变体）

## 原理

```
launchd 每天 8:00（错过则唤醒后补跑）
  └─ run.sh（注入 DINGTALK_WEBHOOK）
       └─ send_ai_daily.py（纯 Python 3.9 标准库，零第三方依赖）
            ├─ 抓 history.php → 筛选出昨天的全部期数（约 5 期）
            ├─ 逐期抓详情页 → 解析分类 / 标题 / 正文
            ├─ 抓 changelog_rss.php → 筛选 Claude Code / Codex 各最新 5 条
            └─ 组装成两条 markdown → POST 到钉钉群机器人 webhook
```

## 一、获取钉钉 webhook（一次性）

1. 打开钉钉，进入一个群（或新建一个「我自己」的群）
2. 群设置 → **智能群助手** → **添加机器人** → **自定义**
3. 安全设置选择**「自定义关键词」**，填入 `AI日报`（消息标题里必须包含该词，否则被拒）
4. 添加成功后复制 **Webhook 地址**（`https://oapi.dingtalk.com/robot/send?access_token=...`）

## 二、配置

把 webhook 填进 `run.sh`：

```bash
export DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=你的access_token"
```

## 三、手动测试

```bash
# 预览消息内容（不发）
/usr/bin/python3 send_ai_daily.py --dry-run

# 正式发送昨天的日报 + 最近24小时工具速报
DINGTALK_WEBHOOK="你的webhook" /usr/bin/python3 send_ai_daily.py

# 补发指定日期的 AI 日报（工具速报仍按 Claude Code / Codex 各最新 5 条）
DINGTALK_WEBHOOK="你的webhook" DAILY_DATE=2026-08-01 /usr/bin/python3 send_ai_daily.py
```

确认手机钉钉群里收到消息后，继续下一步。

## 四、安装定时任务（每天早上 8 点）

用 **launchd**（macOS 自带）而不是 crontab：笔记本睡眠/关机时错过的任务，
launchd 会在唤醒/开机后**自动补跑**，cron 不会。

```bash
# 一次性：安装并启动定时任务
cp com.guanhaitao.ai-daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.guanhaitao.ai-daily.plist
```

确认任务已注册：

```bash
launchctl list | grep ai-daily
# → - 0 com.guanhaitao.ai-daily
```

运行日志写在 `push.log`，发送失败排查：

```bash
tail -20 push.log
```

其他管理命令：

```bash
launchctl unload ~/Library/LaunchAgents/com.guanhaitao.ai-daily.plist   # 停用
launchctl kickstart gui/$(id -u)/com.guanhaitao.ai-daily                 # 立即触发一次
```

## 常见问题

| 现象 | 原因 / 解决 |
|------|------------|
| 发送后返回 `keywords not in content` | 机器人安全设置选了「自定义关键词」，但消息里没有该词。把关键词设为 `AI日报`（消息标题即包含），或改用「加签」并把 Secret 配置进脚本 |
| 发送失败 `invalid signature` | 机器人选了「加签」安全设置，需要在脚本里用 Secret 计算签名。可改回「自定义关键词」 |
| 早上 8 点没收到 | 先看 `tail -20 push.log`；再确认 launchd 任务已加载（`launchctl list \| grep ai-daily`）；笔记本睡眠/关机错过的任务会在唤醒后补跑 |
| 当天没内容 | 网站偶尔无更新或解析失败，日志会打印每期的抓取情况 |

## 文件说明

| 文件 | 作用 |
|------|------|
| `send_ai_daily.py` | 抓取、解析、组装、发送（纯标准库） |
| `run.sh` | launchd 入口：注入 webhook，日志重定向到 `push.log` |
| `com.guanhaitao.ai-daily.plist` | launchd 定时任务定义（每天 8:00，需复制到 `~/Library/LaunchAgents/`） |
| `push.log` | 运行日志（自动生成） |