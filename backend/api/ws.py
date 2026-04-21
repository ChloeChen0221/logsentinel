"""
WebSocket 告警实时推送

订阅 Redis pub/sub `alerts:new` 频道 → 转发给客户端。
多 API 副本各自订阅，都能收到同一条消息。
"""
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from database.redis import get_redis_client
from engine.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["websocket"])


ALERTS_CHANNEL = "alerts:new"


@router.websocket("/ws/alerts")
async def alerts_ws(websocket: WebSocket):
    """接受 WebSocket 连接并订阅 Redis alerts:new 频道"""
    await websocket.accept()
    logger.info("ws_client_connected", client=str(websocket.client))

    redis = get_redis_client()
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(ALERTS_CHANNEL)
        async for message in pubsub.listen():
            if message is None:
                continue
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            try:
                await websocket.send_text(data)
            except Exception as e:
                logger.info("ws_send_failed", error=str(e))
                break
    except WebSocketDisconnect:
        logger.info("ws_client_disconnected", client=str(websocket.client))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("ws_error", error=str(e))
    finally:
        try:
            await pubsub.unsubscribe(ALERTS_CHANNEL)
            await pubsub.aclose()
        except Exception:
            pass
