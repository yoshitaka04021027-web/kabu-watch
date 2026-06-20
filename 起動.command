#!/bin/bash
# 日本株ウォッチ ランチャー（ダブルクリックで起動）
cd "$(dirname "$0")/app" || exit 1
echo "日本株ウォッチ をこのMacだけで開ける状態で起動します..."
python3 app.py
