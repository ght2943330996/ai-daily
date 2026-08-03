#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
钉钉 AI 日报机器人：每天早上 8 点推送「大黑AI速报」昨天的 AI 新闻汇总
+ 「大黑AI工具速报」最近 24 小时新收录的 AI 工具版本更新。

用法：
    DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=xxx" python3 send_ai_daily.py
    DAILY_DATE=2026-08-01 DINGTALK_WEBHOOK=... python3 send_ai_daily.py   # 手动补发指定日期
    DINGTALK_WEBHOOK=... python3 send_ai_daily.py --dry-run              # 只组装打印，不发送

默认日期：本地手动运行发「昨天」；GitHub Actions 每天 8:00 定时运行时发「今天」
（此时网站当天已更新数期）。DAILY_DATE 可覆盖。

仅依赖 Python 3.9 标准库（urllib / html.parser / email.utils），无需第三方包。
"""

import datetime
import email.utils
import html
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from html.parser import HTMLParser

BASE_URL = "https://news.daheiai.com/"
HISTORY_URL = BASE_URL + "history.php"
REALTIME_URL = BASE_URL + "realtime.php?file="
CHANGELOG_RSS_URL = BASE_URL + "changelog_rss.php"
SITE_URL = "https://news.daheiai.com/index.php"
CHANGELOG_URL = "https://news.daheiai.com/changelog.php"

# 标题含这些关键词的视为预发布版本（nightly / alpha / beta / preview / pr 分支）
PRERELEASE_RE = re.compile(
    r"(?i)nightly|alpha|beta|preview|pr-|rc\b|\.rc\.|\bcanary\b"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

WHITESPACE_RE = re.compile(r"\s+")


def fetch(url, timeout=30):
    """抓取网页，返回 UTF-8 解码后的文本。"""
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def clean_text(s):
    """压缩多余空白，去掉首尾空格。"""
    return WHITESPACE_RE.sub(" ", s).strip()


# ---------------------------------------------------------------- 解析器 --

class HistoryParser(HTMLParser):
    """解析 history.php：收集每一期（日期 + file 参数）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.issues = []          # [(date_str, file_param)]
        self._cur_link = None     # 当前 <a> 的 file 参数
        self._in_date = False
        self._date_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "realtime.php?file=" in attrs.get("href", ""):
            self._cur_link = attrs["href"].split("file=", 1)[1]
        elif tag == "span" and "history-date" in attrs.get("class", ""):
            self._in_date = True
            self._date_parts = []

    def handle_data(self, data):
        if self._in_date:
            self._date_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "span" and self._in_date:
            date_str = clean_text("".join(self._date_parts))
            self._in_date = False
            if self._cur_link:
                self.issues.append((date_str, self._cur_link))
                self._cur_link = None


class RealtimeParser(HTMLParser):
    """解析某期详情页：期号标题、AI 总结、分类 +（标题, 正文, 来源链接）列表。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.issue_title = ""      # 如 "2026-08-02 12:01 · 第1600期"
        self.ai_summary = ""       # AI 总结文本
        self.sections = []         # [(分类名, [(标题, 正文, [链接...]), ...])]

        self._in_banner_date = False
        self._in_summary = False
        self._skip_summary_text = False
        self._summary_parts = []
        self._cur_category = None
        self._prev_category = None
        self._cat_parts = []
        self._cur_article = None   # {category, title, body_parts, links, in_title, in_body, in_link}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        class_ = attrs.get("class", "")

        if tag == "p" and "banner-date" in class_:
            self._in_banner_date = True
        elif tag == "section" and "ai-summary" in class_:
            self._in_summary = True
            self._summary_parts = []
        elif tag == "span" and "section-label" in class_:
            self._skip_summary_text = True     # 跳过 "◆ AI 总结" 标签文本
        elif tag == "section" and "content-block" in class_:
            self._cur_category = None
        elif tag == "h2" and "category-header" in class_:
            self._cur_category = ""
            self._cat_parts = []
        elif tag == "article" and "article-item" in class_:
            self._cur_article = {
                "category": self._cur_category,
                "title_parts": [],
                "body_parts": [],
                "links": [],
                "in_title": False,
                "in_body": False,
                "in_link": False,
            }
        elif tag == "h3" and "article-title" in class_ and self._cur_article:
            self._cur_article["in_title"] = True
        elif tag == "div" and "article-body" in class_ and self._cur_article:
            self._cur_article["in_body"] = True
        elif tag == "a" and "ref-link" in class_ and self._cur_article:
            self._cur_article["in_link"] = True
            href = attrs.get("href", "")
            if href.startswith("http"):
                self._cur_article["links"].append(href)

    def handle_data(self, data):
        if self._in_banner_date:
            self.issue_title += data
        elif self._in_summary:
            if not self._skip_summary_text:
                self._summary_parts.append(data)
        elif self._cur_category == "":     # 正在解析 <h2> 分类名
            self._cat_parts.append(data)
        elif self._cur_article:
            if self._cur_article["in_link"]:
                pass                         # 引用链接文本（[4]）不收集
            elif self._cur_article["in_title"]:
                self._cur_article["title_parts"].append(data)
            elif self._cur_article["in_body"]:
                self._cur_article["body_parts"].append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self._in_banner_date:
            self._in_banner_date = False
            self.issue_title = clean_text(self.issue_title)
        elif tag == "section" and self._in_summary:
            self._in_summary = False
            self.ai_summary = clean_text("".join(self._summary_parts))
        elif tag == "h2" and self._cur_category == "":
            # </h2> 时确定分类名：优先用本次收集的文本，否则继承上一分类
            name = clean_text("".join(self._cat_parts))
            if not name:
                name = self._prev_category
            self._cur_category = name
            self._prev_category = name
            self._cat_parts = []
        elif tag == "h3" and self._cur_article:
            self._cur_article["in_title"] = False
        elif tag == "div" and self._cur_article and self._cur_article["in_body"]:
            self._cur_article["in_body"] = False
        elif tag == "a" and self._cur_article and self._cur_article["in_link"]:
            self._cur_article["in_link"] = False
        elif tag == "article" and self._cur_article:
            title = clean_text("".join(self._cur_article["title_parts"]))
            body = clean_text("".join(self._cur_article["body_parts"]))
            # 去掉正文里残留的引用角标，如 "[4]"
            body = re.sub(r"\[[0-9]+\]", "", body)
            body = clean_text(body)
            if title or body:
                self.sections.append((self._cur_article["category"], title, body,
                                      self._cur_article["links"]))
            self._cur_article = None


# ---------------------------------------------------------------- 数据层 --

def get_issues_on_date(date_str):
    """抓历史页，返回某一天（YYYY-MM-DD）的所有期 [(date_str, file)]，按时间排序。"""
    page = fetch(HISTORY_URL)
    parser = HistoryParser()
    parser.feed(page)
    issues = [t for t in parser.issues if t[0].startswith(date_str)]
    issues.sort(key=lambda t: t[0])
    return issues


def get_issue_detail(file_param):
    """抓取并解析某一期详情页。"""
    page = fetch(REALTIME_URL + urllib.parse.quote(file_param))
    parser = RealtimeParser()
    parser.feed(page)
    return parser


# ---------------------------------------------------------------- 工具速报 --

def get_changelog_items(tracked_tools):
    """抓取工具速报 RSS，返回 [{'title','tool','time','link','desc'}]，
    仅包含 tracked_tools 中列出的工具（如 ["Claude Code", "Codex"]）。"""
    page = fetch(CHANGELOG_RSS_URL)
    items = []
    for block in re.findall(r"<item>(.*?)</item>", page, re.S):
        def field(tag):
            m = re.search(r"<%s>(.*?)</%s>" % (tag, tag), block, re.S)
            return m.group(1).strip() if m else ""

        title = field("title")
        pub = field("pubDate")
        try:
            dt = email.utils.parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            continue
        tool = field("category") or ""
        if tool not in tracked_tools:
            continue
        # description 到英文段前为止（<h3>English</h3>），取中文内容
        desc = field("description")
        m = re.search(r"<h3>English</h3>", desc, re.I)
        if m:
            desc = desc[:m.start()]
        desc = re.sub(r"<[^>]+>", "", desc)      # 去 HTML 标签
        desc = html.unescape(desc)
        desc = "\n".join(l.rstrip() for l in desc.splitlines() if l.strip())
        items.append({
            "title": title,
            "tool": tool,
            "time": dt,
            "link": field("link") or "",
            "desc": desc,
        })
    items.sort(key=lambda x: x["time"], reverse=True)
    return items


# ---------------------------------------------------------------- 消息组装 --

def _truncate(text, limit=120):
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def build_message(issues, date_str):
    """把一天的所有期组装成一条钉钉 markdown 消息文本。"""
    month, day = int(date_str[5:7]), int(date_str[8:10])
    disp_date = f"{month}月{day}日"

    total_items = 0
    for issue in issues:
        total_items += sum(len(sec[3]) for sec in issue.sections) if issue.sections else 0

    lines = []
    lines.append(f"## 📰 AI日报 · {disp_date}（共{total_items}条快讯）")

    # 每期一行链接
    issue_lines = []
    for issue in issues:
        # issue_title 形如 "2026-08-02 12:01 · 第1600期"
        m = re.search(r"(\d{2}:\d{2})", issue.issue_title)
        time_str = m.group(1) if m else ""
        url = BASE_URL + "realtime.php?file=" + urllib.parse.quote(issue.file_param)
        issue_lines.append(f"**{time_str}** [{issue.issue_title.split(' · ')[-1]}]({url})")
    if issue_lines:
        lines.append("> " + "　".join(issue_lines))

    # AI 总结（可选）
    if any(getattr(i, "ai_summary", "") for i in issues):
        # 仅当存在非空总结时显示（通常为最新一期）
        summary = next((i.ai_summary for i in issues if i.ai_summary), "")
        if summary:
            lines.append("")
            lines.append(f"> 💡 **AI总结**：{_truncate(summary, 150)}")

    # 按分类分组：分类 -> 条目列表
    grouped = {}
    for issue in issues:
        for category, title, body, links in issue.sections:
            grouped.setdefault(category or "其他", []).append((title, body, links))

    for category, items in grouped.items():
        lines.append("")
        lines.append(f"### **{category}**（{len(items)}）")
        for title, body, links in items:
            line = f"- **{title}**"
            if body and body != title:
                line += f"：{_truncate(body)}"
            # 角标形式的来源链接，如 [1](url) [2](url)，点击直达原帖
            for idx, url in enumerate(links[:5], 1):
                line += f" [[{idx}]]({url})"
            lines.append(line)

    lines.append("")
    lines.append("---")
    lines.append(f"来源：[大黑AI速报]({SITE_URL})")
    return "\n".join(lines)


# ---------------------------------------------------------------- 工具速报消息 --

# 关注哪些工具（网站 RSS 中的 category 名）
TRACKED_TOOLS = ["Claude Code", "Codex"]
# 每个工具展示最新几条更新
TOOLS_PER_COUNT = 5
# 只推正式版，过滤掉预发布（nightly/alpha/beta/preview/rc/pr 分支）
STABLE_ONLY = True
# 排除非主线分支（如 Codex 的 rusty-v8 变体）
EXCLUDE_TITLE_RE = re.compile(r"(?i)rusty-v8|^Codex (claude|cli)[\s-]")

# 正式版优先于预发布；同工具内再按版本号排序（预发布排在正式版之后）
def _version_sort_key(item):
    is_pre = 1 if PRERELEASE_RE.search(item["title"]) else 0
    return (is_pre, _version_key(item["title"]))


def _changelog_entry_lines(item):
    """单条版本更新 → 消息行列表（含是否预发布的标注说明）。"""
    prerelease = bool(PRERELEASE_RE.search(item["title"]))
    # 去掉标题里已有的 "(预发布)" 后缀，统一用标注
    title = re.sub(r"\s*\(预发布\)\s*$", "", item["title"])
    marker = "（预发布）" if prerelease else ""
    # 收录时间，如（07-25）
    when = item["time"].strftime("%m-%d")
    lines = [f"- **{title}**（{when}）{marker}"]

    desc = item.get("desc", "").strip()
    # 只保留 " - " 开头的顶级变更条目（缩进的子条目丢弃），去掉标题行
    bullets = [b.strip() for b in desc.split("\n")
               if b.strip().startswith("-") and not b.startswith("  ")][:6]
    if bullets:
        for b in bullets:
            lines.append(f"  - {_truncate(b.lstrip('- '), 80)}")
    else:
        # 没有条目列表时，去掉标题行后取正文前几句
        body = "\n".join(l for l in desc.split("\n")
                         if not l.strip().startswith("#"))
        body = clean_text(body)
        if body:
            lines.append(f"  - {_truncate(body, 80)}")
    return lines


def _version_key(title):
    """提取标题里的版本号用于排序：v0.147.0-alpha.4 → (0,147,0, -1, 4)。"""
    m = re.search(r"v?(\d+(?:\.\d+)+)", title)
    if not m:
        return (0, 0, 0, 0, 0)
    nums = [int(p) for p in m.group(1).split(".")]
    # 预发布(含 alpha/beta/preview/rc)排在正式版之后
    is_pre = 1 if PRERELEASE_RE.search(title) else 0
    tail = 0
    m2 = re.search(r"(?:alpha|beta|preview|rc)[.\-]?(\d+)", title, re.I)
    if m2:
        tail = int(m2.group(1))
    return tuple(nums + [is_pre, tail])


def build_changelog_message(items):
    """把每个关注工具的最新若干条更新组装成一条钉钉 markdown 消息文本。"""
    lines = [f"## 🔧 AI日报 · 工具速报（{ ' / '.join(TRACKED_TOOLS) }）"]

    for tool in TRACKED_TOOLS:
        tool_items = [i for i in items if i["tool"] == tool
                      and not EXCLUDE_TITLE_RE.search(i["title"])]
        if STABLE_ONLY:
            tool_items = [i for i in tool_items
                          if not PRERELEASE_RE.search(i["title"])]
        tool_items.sort(key=_version_sort_key, reverse=True)
        tool_items = tool_items[:TOOLS_PER_COUNT]
        if not tool_items:
            continue
        lines.append("")
        lines.append(f"### **{tool}**（最新 {len(tool_items)} 条）")
        for item in tool_items:
            lines.extend(_changelog_entry_lines(item))

    lines.append("")
    lines.append("---")
    lines.append(f"来源：[大黑AI工具速报]({CHANGELOG_URL})")
    return "\n".join(lines)


# ---------------------------------------------------------------- 发送 --

def send_to_dingtalk(webhook, title, text):
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if result.get("errcode") != 0:
        raise RuntimeError("钉钉返回错误: %s" % result)
    return result


# ---------------------------------------------------------------- main --

def main():
    webhook = os.environ.get("DINGTALK_WEBHOOK", "").strip()
    date_str = os.environ.get("DAILY_DATE", "").strip()
    dry_run = "--dry-run" in sys.argv

    if not date_str:
        # GitHub Actions 每天 8:00 定时触发时默认发"今天"的日报（此时网站当天已有数期）；
        # 本地手动运行默认发"昨天"，两者行为一致地由 DAILY_DATE 覆盖。
        if os.environ.get("GITHUB_ACTIONS") == "true":
            date_str = datetime.date.today().strftime("%Y-%m-%d")
        else:
            date_str = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        print("DAILY_DATE 格式应为 YYYY-MM-DD", file=sys.stderr)
        sys.exit(2)
    if not webhook and not dry_run:
        print("缺少环境变量 DINGTALK_WEBHOOK（或使用 --dry-run 预览）", file=sys.stderr)
        sys.exit(2)

    print(f"[{datetime.datetime.now():%H:%M:%S}] 目标日期: {date_str}")

    # 1. 历史页 → 昨日期期
    try:
        issues_meta = get_issues_on_date(date_str)
    except Exception as e:
        print(f"抓取历史页失败: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"找到 {len(issues_meta)} 期: {[t[0] for t in issues_meta]}")

    if not issues_meta:
        print("当天没有任何期数，无需推送")
        return

    # 2. 逐期抓详情
    parsed = []
    for date_time, file_param in issues_meta:
        try:
            detail = get_issue_detail(file_param)
            detail.file_param = file_param
            parsed.append(detail)
            print(f"  解析 {date_time}: {len(detail.sections)} 条快讯")
        except Exception as e:
            print(f"  抓取 {date_time} 失败，跳过: {e}", file=sys.stderr)

    if not parsed:
        print("所有期数抓取失败，退出", file=sys.stderr)
        sys.exit(1)

    # 3. 组装（AI 日报）
    text = build_message(parsed, date_str)
    month, day = int(date_str[5:7]), int(date_str[8:10])
    title = f"AI日报 {month}月{day}日"
    print("\n" + "=" * 60)
    print(text)
    print("=" * 60)

    # 4. 工具速报：只关注 TRACKED_TOOLS，各取最新 TOOLS_PER_COUNT 条
    try:
        tool_items = get_changelog_items(TRACKED_TOOLS)
        tool_text = build_changelog_message(tool_items)
        print(f"工具速报: {len(tool_items)} 条（{ {t: sum(1 for i in tool_items if i['tool']==t) for t in TRACKED_TOOLS} }）")
        print("\n" + "=" * 60)
        print(tool_text)
        print("=" * 60)
    except Exception as e:
        print(f"抓取工具速报失败，跳过: {e}", file=sys.stderr)
        tool_text = None

    # 5. 发送
    if dry_run:
        print("\n[dry-run] 未发送。")
        return
    result = send_to_dingtalk(webhook, title, text)
    print(f"AI日报发送成功: {result.get('errmsg', 'ok')}")
    if tool_text:
        result2 = send_to_dingtalk(webhook, f"{title} · 工具速报", tool_text)
        print(f"工具速报发送成功: {result2.get('errmsg', 'ok')}")


if __name__ == "__main__":
    main()
