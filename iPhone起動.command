#!/bin/bash
# 日本株ウォッチ iPhone用ランチャー（同じWi-Fi内の端末にも公開）
cd "$(dirname "$0")/app" || exit 1
echo "日本株ウォッチ をiPhoneからも開ける状態で起動します..."
HOST=0.0.0.0 python3 app.py
