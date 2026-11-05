"""Event clustering: title+sector join and dual heat scores."""

from __future__ import annotations

from datetime import datetime, timedelta

from news_radar import config as cfg
from news_radar.db import (
    attach_article_cluster,
    heat_map,
    init_db,
    insert_article,
    link_article_sectors,
    list_recent_clusters,
    sector_heat_between,
)
from news_radar.dedupe import assign_cluster


def _patch_db(tmp_path, monkeypatch):
    db_path = tmp_path / "radar.db"
    monkeypatch.setattr(cfg, "DB_PATH", db_path)
    monkeypatch.setattr(cfg, "DATA_DIR", tmp_path)
    import news_radar.db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cfg, "EVENT_CLUSTER_ENABLED", True)
    monkeypatch.setattr(cfg, "EVENT_CLUSTER_HEAT", False)
    monkeypatch.setattr(cfg, "EVENT_CLUSTER_SIM", 0.45)
    init_db()


def test_assign_cluster_merges_rewrites():
    recent = [
        {
            "id": 1,
            "title": "半导体设备订单回暖 多家厂商扩产",
            "sectors": {"半导体"},
        }
    ]
    # Same story, lightly rewritten — should join.
    assert (
        assign_cluster(
            "多家半导体设备厂商扩产 订单回暖",
            {"半导体"},
            recent,
            threshold=0.45,
        )
        == 1
    )
    # Same keywords but different sector — must not join.
    assert (
        assign_cluster(
            "半导体设备订单回暖 多家厂商扩产",
            {"军工"},
            recent,
            threshold=0.45,
        )
        is None
    )
    # Unrelated title — must not join.
    assert (
        assign_cluster(
            "白酒春节备货启动 渠道库存回升",
            {"半导体"},
            recent,
            threshold=0.45,
        )
        is None
    )


def test_attach_and_event_heat(tmp_path, monkeypatch):
    _patch_db(tmp_path, monkeypatch)
    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")

    def _ins(fp, title, source, weight=1.0):
        aid = insert_article(
            {
                "fingerprint": fp,
                "source": source,
                "title": title,
                "summary": "",
                "url": "",
                "published_at": stamp,
                "fetched_at": stamp,
            }
        )
        assert aid
        link_article_sectors(
            aid, [{"sector": "半导体", "keyword": "半导体", "weight": weight}]
        )
        cid = attach_article_cluster(
            aid, title=title, sectors=["半导体"], source=source
        )
        return aid, cid

    a1, c1 = _ins(
        "fp1",
        "半导体设备订单回暖 多家厂商扩产",
        "财联社电报",
        weight=2.0,
    )
    a2, c2 = _ins(
        "fp2",
        "多家半导体设备厂商扩产 订单回暖明显",
        "东财要闻",
        weight=1.5,
    )
    a3 = insert_article(
        {
            "fingerprint": "fp3",
            "source": "新浪财经",
            "title": "锂电隔膜涨价落地 龙头议价能力增强",
            "summary": "",
            "url": "",
            "published_at": stamp,
            "fetched_at": stamp,
        }
    )
    assert a3
    link_article_sectors(
        a3, [{"sector": "新能源/锂电", "keyword": "锂电", "weight": 3.0}]
    )
    c3 = attach_article_cluster(
        a3,
        title="锂电隔膜涨价落地 龙头议价能力增强",
        sectors=["新能源/锂电"],
        source="新浪财经",
    )
    assert c1 and c2 and c1 == c2
    assert c3 and c3 != c1
    clusters = list_recent_clusters(hours=24)
    assert any(c["id"] == c1 and c["n_articles"] >= 2 and c["n_sources"] >= 2 for c in clusters)

    start = now - timedelta(hours=1)
    end = now + timedelta(hours=1)
    rows = sector_heat_between(start, end)
    semi = next(r for r in rows if r["sector"] == "半导体")
    # Article sum: 2.0 + 1.5 = 3.5；event score: max(2.0,1.5)=2.0 for one cluster.
    assert semi["article_count"] == 2
    assert semi["raw_score"] == 3.5
    assert semi["event_count"] == 1
    assert semi["event_score"] == 2.0
    assert semi["multi_source_events"] == 1
    assert heat_map(rows, score_key="event_score")["半导体"] == 2.0
    assert heat_map(rows, score_key="raw_score")["半导体"] == 3.5
