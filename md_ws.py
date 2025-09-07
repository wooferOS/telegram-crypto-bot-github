"""WebSocket utilities for Binance Spot market data streams.

The module provides a thin manager that can subscribe to multiple streams using
Binance combined stream URLs. Connections are intended for market-data only and
use ``wss://data-stream.binance.vision`` as recommended in the Binance
"Market Data Only" guidelines.

Documentation: https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
"""

from __future__ import annotations

import json
import threading
import time
from typing import Callable, List

try:  # ``websocket-client`` is optional during testing
    import websocket  # type: ignore
except Exception:  # pragma: no cover - module is optional
    websocket = None  # type: ignore

PING_INTERVAL = 20  # seconds, Binance requirement
MAX_MSG_PER_SEC = 5  # incoming rate limit
BASE_WSS_URL = "wss://data-stream.binance.vision"


def build_combined_stream(streams: List[str]) -> str:
    """Return combined stream URL for ``streams``.

    Example::

        build_combined_stream(["btcusdt@bookTicker", "ethusdt@avgPrice"])
    """

    stream_path = "/stream?streams=" + "/".join(streams)
    return f"{BASE_WSS_URL}{stream_path}"


class MarketDataWS:
    """Manage a Binance market-data WebSocket connection.

    The manager keeps track of incoming message counts to enforce the
    5 msg/s guideline and sends ping frames every 20 seconds. It is intentionally
    minimal; production code should handle reconnections and resubscriptions
    after 24h as per Binance limits.
    """

    def __init__(self, streams: List[str], on_message: Callable[[str], None]):
        self.streams = streams
        self.on_message_cb = on_message
        self.ws = None
        self._msg_count = 0
        self._last_sec = int(time.time())

    # --- connection management ---------------------------------------------

    def connect(self) -> None:
        if websocket is None:  # pragma: no cover - depends on optional lib
            raise RuntimeError("websocket-client is required for WS operations")

        url = build_combined_stream(self.streams)
        self.ws = websocket.WebSocketApp(
            url,
            on_message=self._handle_message,
            on_open=lambda ws: self._start_ping_thread(),
        )
        self.ws.run_forever()

    # ------------------------------------------------------------------

    def _handle_message(self, ws, message: str) -> None:
        now = int(time.time())
        if now != self._last_sec:
            self._msg_count = 0
            self._last_sec = now
        self._msg_count += 1
        if self._msg_count > MAX_MSG_PER_SEC:
            ws.close()  # hard stop if flood detected
            return
        self.on_message_cb(message)

    # ------------------------------------------------------------------

    def _start_ping_thread(self) -> None:
        def _run():
            while self.ws and self.ws.keep_running:
                try:
                    self.ws.send(json.dumps({"method": "PING"}))
                except Exception:
                    return
                time.sleep(PING_INTERVAL)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
