"""Collectors: timestamp normalization, CLS parsing, dedupe and source counts."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta

import news_radar.db as db
from news_radar import collect
from news_radar.collect import CN_TZ, cls_sign, norm_time, parse_cls_items
from news_radar.dedupe import drop_seen_titles
from news_radar.engine import filter_new_rows
from news_radar.score import match_sectors


def test_norm_time_formats():
    assert norm_time("1790957269") == datetime.fromtimestamp(1790957269, CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    assert norm_time("1790957269000") == norm_time("1790957269")
    assert norm_time("2026-10-02 21:00:33") == "2026-10-02 21:00:33"
    assert norm_time("2026/10/02 21:00") == "2026-10-02 21:00:00"
    assert norm_time("2026-10-02T21:00:33+08:00") == "2026-10-02 21:00:33"
    assert norm_time("昨天") is None and norm_time("") is None and norm_time("12345") is None


def test_cls_sign_is_md5_of_sha1_sorted_query():
    params = {"rn": "20", "app": "CailianpressWeb", "os": "web"}
    sha = hashlib.sha1(b"app=CailianpressWeb&os=web&rn=20").hexdigest()
    assert cls_sign(params) == hashlib.md5(sha.encode()).hexdigest()


def test_parse_cls_items_title_tags_level():
    rows = parse_cls_items([
        {"id": 1, "ctime": 1790957545, "level": "a", "title": "",
         "brief": "【一艘油轮在霍尔木兹海峡遭不明发射物击中】财联社10月3日电，英国海事贸易行动办公室通报。",
         "subjects": [{"subject_name": "中东冲突"}, {"subject_name": "船舶"}],
         "stock_list": [{"name": "中远海能"}]},
        {"id": 2, "ctime": 1790956922, "title": "", "content": "财联社10月3日电，俄罗斯二季度GDP同比终值增长1.3%。"},
        {"id": 3, "title": "短", "brief": ""},
    ])
    assert len(rows) == 2
    first, second = rows
    assert first["title"] == "一艘油轮在霍尔木兹海峡遭不明发射物击中"
    assert first["summary"] == "英国海事贸易行动办公室通报。"
    assert first["tags"] == ["中东冲突", "船舶", "中远海能"]
    assert first["importance"] == "A" and first["url"].endswith("/detail/1")
    assert first["published_at"] == norm_time(1790957545)
    assert second["title"].startswith("俄罗斯二季度GDP") and second["importance"] is None


def test_drop_seen_titles_catches_reworded_repeat():
    rows = [{"title": "一艘油轮在霍尔木兹海峡遭不明发射物击中"}, {"title": "央行开展逆回购操作"}]
    kept, dropped = drop_seen_titles(rows, ["【一艘油轮在霍尔木兹海峡遭不明发射物击中】"])
    assert dropped == 1 and [r["title"] for r in kept] == ["央行开展逆回购操作"]
    assert drop_seen_titles(rows, [])[1] == 0


def test_filter_new_rows_drops_stale_known_and_seen(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "radar.db")
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    db.init_db()
    now = datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")
    old = (datetime.now(CN_TZ) - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
    db.insert_article({"fingerprint": "f1", "title": "光伏产业链价格全线上涨", "fetched_at": now})
    rows = [
        {"fingerprint": "f1", "title": "光伏产业链价格全线上涨", "published_at": now},
        {"fingerprint": "f2", "title": "光伏产业链价格全线上涨！", "published_at": now},
        {"fingerprint": "f3", "title": "旧闻：八月出口数据", "published_at": old},
        {"fingerprint": "f4", "title": "工信部发布人形机器人新规", "published_at": None},
    ]
    fresh, stats = filter_new_rows(rows)
    assert [r["fingerprint"] for r in fresh] == ["f4"]
    assert stats == {"stale": 1, "known": 1, "seen_dup": 1}


def test_match_sectors_uses_source_tags():
    assert not match_sectors("某公司发布公告", "")
    hits = match_sectors("某公司发布公告", "", ["半导体"])
    assert any(h["sector"] == "半导体" for h in hits)


def test_collect_all_reports_per_source_counts(monkeypatch):
    async def em(client, column, *, source, region="A", limit=30):
        return [{"title": source}] if column == "350" else []

    async def cls(client, limit=50):
        raise RuntimeError("boom")

    async def sina(client, limit=30):
        return [{"title": "s1"}, {"title": "s2"}]

    monkeypatch.setattr(collect, "fetch_eastmoney_column", em)
    monkeypatch.setattr(collect, "fetch_cls_telegraph", cls)
    monkeypatch.setattr(collect, "fetch_sina_finance_roll", sina)
    rows, counts = asyncio.run(collect.collect_all(None))
    assert len(rows) == 3
    assert counts["东财财经"] == 1 and counts["东财股市"] == 0
    assert counts[collect.CLS_SOURCE] == 0 and counts[collect.SINA_SOURCE] == 2
    assert set(counts) == set(collect.SOURCE_NAMES)
