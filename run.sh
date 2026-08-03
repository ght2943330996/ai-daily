#!/bin/bash
# 钉钉 AI 日报入口：每天 8:00 由 GitHub Actions 云端调用（或本地手动调用）。
#
# webhook 通过环境变量 DINGTALK_WEBHOOK 注入：
#   - GitHub Actions：由 workflow 从仓库 Secrets 注入（见 .github/workflows/daily.yml）
#   - 本地手动：DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=..." ./run.sh

: "${DINGTALK_WEBHOOK:?未设置 DINGTALK_WEBHOOK 环境变量（GitHub Actions 中在仓库 Secrets 配置，本地则手动 export）}"

cd "$(dirname "$0")" || exit 1

/usr/bin/python3 send_ai_daily.py >> push.log 2>&1
