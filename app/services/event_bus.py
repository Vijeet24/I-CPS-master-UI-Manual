import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._connections: set[Any] = set()

    async def connect(self, websocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        logger.info("WebSocket client connected", extra={"clients": len(self._connections)})

    def disconnect(self, websocket) -> None:
        self._connections.discard(websocket)
        logger.info("WebSocket client disconnected", extra={"clients": len(self._connections)})

    def publish(self, event_type: str, data: dict) -> None:
        message = json.dumps({"event": event_type, "data": data})
        stale: list[Any] = []
        for connection in self._connections:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(connection.send_text(message))
                else:
                    loop.run_until_complete(connection.send_text(message))
            except RuntimeError:
                try:
                    asyncio.run(connection.send_text(message))
                except Exception:
                    stale.append(connection)
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(connection)


event_bus = EventBus()
