"""Launch the local news-radar dashboard."""

from __future__ import annotations

import logging
import threading
import time
import webbrowser

import uvicorn

from news_radar.config import BROWSER_HOST, HOST, PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _open_browser() -> None:
    time.sleep(1.4)
    webbrowser.open(f"http://{BROWSER_HOST}:{PORT}/")


def main() -> None:
    """Run uvicorn and open the browser."""
    threading.Thread(target=_open_browser, daemon=True).start()
    print(f"新闻雷达: http://{BROWSER_HOST}:{PORT}/")
    print("关掉本窗口即停止")
    uvicorn.run(
        "news_radar.app:app",
        host=HOST,
        port=PORT,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()
