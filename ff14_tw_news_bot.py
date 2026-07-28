#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FF14 台版官網公告 -> Discord 通知機器人

功能：
- 抓取 https://www.ffxiv.com.tw/web/news/news_list.aspx （或指定分類）
- 找出所有公告連結，跟上次記錄比對
- 有新公告就用 Discord Webhook 推播到頻道

用法：
    export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/xxx/xxx"
    python3 ff14_tw_news_bot.py

可用環境變數：
    DISCORD_WEBHOOK_URL   Discord webhook 網址 (必填，否則只會印出結果不會發送)
    NEWS_CATEGORY         要監控的分類，對應官網分類參數：
                          （不設定 = 全部）
                          1 = 活動公告
                          2 = 更新公告
                          3 = 維護公告
                          4 = 其他公告
    STATE_FILE            記錄已通知過的公告 ID 的檔案路徑 (預設: 與腳本同目錄下的 seen_news.json)

建議搭配 cron / 排程器每 5~15 分鐘執行一次。
第一次執行只會「建立記錄」，不會發送任何訊息，避免把現有幾十篇公告一次洗版；
之後每次執行只會通知「新增」的公告。
"""

import json
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.ffxiv.com.tw"

CATEGORY = os.environ.get("NEWS_CATEGORY", "").strip()
if CATEGORY:
    NEWS_LIST_URL = f"{BASE_URL}/web/news/news_list.aspx?category={CATEGORY}"
else:
    NEWS_LIST_URL = f"{BASE_URL}/web/news/news_list.aspx"

STATE_FILE = os.environ.get(
    "STATE_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_news.json"),
)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def fetch_news_list():
    resp = requests.get(NEWS_LIST_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    # 網站是繁中內容，避免編碼判斷錯誤
    if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def parse_news(html):
    """解析消息列表頁面，回傳 [{id, title, url, date}, ...]，由新到舊排列。"""
    soup = BeautifulSoup(html, "html.parser")
    news_items = []
    seen_in_page = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"news_content\.aspx\?id=([A-Za-z0-9]+)", href)
        if not m:
            continue

        news_id = m.group(1)
        if news_id in seen_in_page:
            continue

        title = a.get_text(strip=True)
        if not title:
            continue

        seen_in_page.add(news_id)

        # 嘗試從同一個表格列（<tr>）抓日期，格式通常是 YYYY/MM/DD
        date_str = None
        row = a.find_parent("tr")
        if row is not None:
            row_text = row.get_text(" ", strip=True)
            date_match = re.search(r"\d{4}/\d{2}/\d{2}", row_text)
            if date_match:
                date_str = date_match.group(0)

        full_url = href if href.startswith("http") else BASE_URL + href

        news_items.append(
            {
                "id": news_id,
                "title": title,
                "url": full_url,
                "date": date_str,
            }
        )

    return news_items


def load_seen_ids():
    if not os.path.exists(STATE_FILE):
        return set()
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("seen_ids", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen_ids(ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"seen_ids": sorted(ids)}, f, ensure_ascii=False, indent=2)


def send_discord_message(item):
    if not DISCORD_WEBHOOK_URL:
        print(f"[未設定 DISCORD_WEBHOOK_URL，僅顯示] {item['title']} -> {item['url']}")
        return

    embed = {
        "title": item["title"],
        "url": item["url"],
        "color": 0x2B6CB0,
        "footer": {"text": "FINAL FANTASY XIV 繁體中文版官網"},
    }
    if item.get("date"):
        embed["description"] = f"發布日期：{item['date']}"

    payload = {
        "username": "FF14 台版公告",
        "embeds": [embed],
    }

    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=15)
    if resp.status_code >= 300:
        print(
            f"發送 Discord 訊息失敗（{resp.status_code}）：{resp.text}",
            file=sys.stderr,
        )


def main():
    html = fetch_news_list()
    news_items = parse_news(html)

    if not news_items:
        print(
            "沒有抓到任何公告連結，官網結構可能已變更，請檢查 parse_news() 的選擇器。",
            file=sys.stderr,
        )
        sys.exit(1)

    seen_ids = load_seen_ids()
    is_first_run = len(seen_ids) == 0

    new_items = [item for item in news_items if item["id"] not in seen_ids]

    if is_first_run:
        print(f"首次執行：記錄目前 {len(news_items)} 筆公告，之後只會通知新公告，本次不發送訊息。")
    elif new_items:
        # 由舊到新依序發送，讓 Discord 頻道裡的順序也是由舊到新
        for item in reversed(new_items):
            send_discord_message(item)
            print(f"已發送：{item['title']}")
    else:
        print("沒有新公告。")

    all_ids = seen_ids | {item["id"] for item in news_items}
    save_seen_ids(all_ids)


if __name__ == "__main__":
    main()
