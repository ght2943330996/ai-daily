# 钉钉 AI 日报机器人

每天上午 7:47 推送以下内容到你的手机钉钉（**两条消息**），10:17 有自动补发兜底（防止 GitHub 定时偶发延迟/漏跑）：

1. **📰 AI日报**：把 [大黑AI速报](https://news.daheiai.com/index.php)（每 4 小时更新一期的 AI 新闻快讯站）**当天**的新闻汇总
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
GitHub Actions 云端定时（不依赖电脑开机），双 workflow 兜底：
  daily.yml    07:47 主发 → 成功后把日期写回 last_sent.txt（commit 到仓库）
  catchup.yml  10:17 检查 last_sent.txt 不是今天 → 说明主发漏了，自动补发
  └─ run.sh（从仓库 Secrets 注入 DINGTALK_WEBHOOK）
       └─ send_ai_daily.py（纯 Python 3.9 标准库，零第三方依赖）
            ├─ 抓 history.php → 筛选出当天的全部期数（约 5 期）
            ├─ 逐期抓详情页 → 解析分类 / 标题 / 正文
            ├─ 抓 changelog_rss.php → 筛选 Claude Code / Codex 各最新 5 条
            └─ 组装成两条 markdown → POST 到钉钉群机器人 webhook
```

> 为什么要双 workflow？GitHub 的 schedule 在整点（尤其 00:00 UTC）排队高峰，实测会
> 延迟近 2 小时甚至整次漏掉。两个 cron 刻意避开整点，并用 `last_sent.txt` 记录
> 发送结果，主发漏了由补发兜住（宁多勿漏）。

## 一、获取钉钉 webhook（一次性）

1. 打开钉钉，进入一个群（或新建一个「我自己」的群）
2. 群设置 → **智能群助手** → **添加机器人** → **自定义**
3. 安全设置选择**「自定义关键词」**，填入 `AI日报`（消息标题里必须包含该词，否则被拒）
4. 添加成功后复制 **Webhook 地址**（`https://oapi.dingtalk.com/robot/send?access_token=...`）

## 二、配置

webhook **不要写进代码或提交到仓库**，通过环境变量注入：

- **云端（GitHub Actions）**：配置为仓库 Secret `DINGTALK_WEBHOOK`（见第四节）
- **本地手动**：运行时通过环境变量传入

```bash
export DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=你的access_token"
```

## 三、手动测试

```bash
# 预览消息内容（不发；本地默认发昨天，GITHUB_ACTIONS=true 时发当天）
/usr/bin/python3 send_ai_daily.py --dry-run

# 正式发送当天日报 + 工具速报（GitHub Actions 行为）
GITHUB_ACTIONS=true DINGTALK_WEBHOOK="你的webhook" /usr/bin/python3 send_ai_daily.py

# 补发指定日期的 AI 日报（工具速报仍按 Claude Code / Codex 各最新 5 条）
DINGTALK_WEBHOOK="你的webhook" DAILY_DATE=2026-08-01 /usr/bin/python3 send_ai_daily.py
```

确认手机钉钉群里收到消息后，继续下一步。

## 四、安装定时任务（每天 7:47 主发 + 10:17 兜底，云端运行）

用 **GitHub Actions** 在云端定时执行，**不依赖电脑开机/睡眠状态**。
webhook 通过仓库 Secrets 注入，**不会出现在代码里**。

### 首次配置

```bash
# 1. 建私有仓库并推送（webhook 不会进代码，仓库私密更安心）
gh repo create ai-daily --private
git remote add origin https://github.com/<你的账号>/ai-daily.git
git push -u origin main

# 2. 把钉钉 webhook 设为仓库 Secret
#    提示粘贴时直接输入 webhook 地址（https://oapi.dingtalk.com/robot/send?access_token=...）
gh secret set DINGTALK_WEBHOOK -R <你的账号>/ai-daily

# 3. 配置完成后，GitHub 每天 07:47（北京时间）主发、10:17 自动补发兜底
#    手动触发一次验证：
gh workflow run daily.yml -R <你的账号>/ai-daily
gh run watch -R <你的账号>/ai-daily
```

### 查看运行情况

```bash
gh run list -R <你的账号>/ai-daily        # 最近运行
gh run view <run_id> -R <你的账号>/ai-daily   # 查看日志（含发送结果）
```

运行日志在 Actions 运行记录里；若单日发送失败（网络抖动等），可在 Actions 页面
「Re-run jobs」重跑，或在仓库 Settings → Secrets 检查 webhook 配置。

> 可选兜底：本地 launchd 任务（`~/Library/LaunchAgents/com.guanhaitao.ai-daily.plist`）
> 可在电脑开机时补发一次，作为云端方案的补充。不需要可 `launchctl unload` 停用。

## 常见问题

| 现象 | 原因 / 解决 |
|------|------------|
| 发送后返回 `keywords not in content` | 机器人安全设置选了「自定义关键词」，但消息里没有该词。把关键词设为 `AI日报`（消息标题即包含），或改用「加签」并把 Secret 配置进脚本 |
| 发送失败 `invalid signature` | 机器人选了「加签」安全设置，需要在脚本里用 Secret 计算签名。可改回「自定义关键词」 |
| 早上 7:47 没收到 | 主发可能被延迟，10:17 有 catchup.yml 自动补发兜底；仍未收到再 `gh run list -R <账号>/ai-daily` 看运行是否成功，查 Actions 日志里的发送结果，最后确认 `gh secret list` 里 `DINGTALK_WEBHOOK` 存在 |
| Actions 定时偶发没触发 | GitHub 不保证 cron 100% 触发（整点高峰尤其严重）。已用双 workflow 兜底：07:47 主发 + 10:17 自动补发；也可在 Actions 页面手动「Run workflow」补发当天 |
| 工具速报条数不足 5 | 过滤掉预发布（nightly/alpha/beta）后正式版不够 5 条时，展示实际数量（正常现象） |
| 当天没内容 | 网站偶尔无更新或解析失败，日志会打印每期的抓取情况 |

## 文件说明

| 文件 | 作用 |
|------|------|
| `send_ai_daily.py` | 抓取、解析、组装、发送（纯标准库） |
| `run.sh` | 推送入口：读 `DINGTALK_WEBHOOK` 环境变量，Actions 下日志直达运行记录 |
| `.github/workflows/daily.yml` | GitHub Actions 定时任务（每天 07:47 主发，失败自动重试 3 次，成功后更新 `last_sent.txt` 标记） |
| `.github/workflows/catchup.yml` | 兜底任务（每天 10:17，检测当天未发送则自动补发） |
| `last_sent.txt` | 最近一次成功发送的日期（发送成功时自动提交，勿手动修改） |
| `com.guanhaitao.ai-daily.plist` | 可选：本地 launchd 兜底任务（电脑开机时补发） |
| `push.log` | 本地手动运行日志（自动生成，已被 gitignore） |