"""
Loki 客户端单元测试
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from backend.engine.loki_client import LokiClient, LokiQueryError, LogEntry


@pytest.mark.asyncio
async def test_build_query_basic():
    """测试基础 LogQL 查询构造"""
    client = LokiClient()
    
    query = client._build_query(namespace="demo")
    
    assert query == '{namespace="demo"}'


@pytest.mark.asyncio
async def test_build_query_with_labels():
    """测试带标签的 LogQL 查询构造"""
    client = LokiClient()
    
    query = client._build_query(
        namespace="demo",
        labels={"app": "myapp", "env": "prod"}
    )
    
    assert 'namespace="demo"' in query
    assert 'app="myapp"' in query
    assert 'env="prod"' in query


@pytest.mark.asyncio
async def test_build_query_with_keyword():
    """测试带关键词的 LogQL 查询构造"""
    client = LokiClient()
    
    query = client._build_query(
        namespace="demo",
        keyword="ERROR"
    )
    
    assert query == '{namespace="demo"} |= "ERROR"'


@pytest.mark.asyncio
async def test_query_range_success():
    """测试成功查询 Loki"""
    client = LokiClient()
    
    # Mock Loki 响应
    mock_response = {
        "status": "success",
        "data": {
            "result": [
                {
                    "stream": {
                        "namespace": "demo",
                        "pod": "test-pod",
                        "container": "app"
                    },
                    "values": [
                        ["1738656615000000000", "ERROR: test message 1"],
                        ["1738656616000000000", "ERROR: test message 2"]
                    ]
                }
            ]
        }
    }
    
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = AsyncMock(
            status_code=200,
            json=lambda: mock_response
        )
        mock_get.return_value.raise_for_status = lambda: None
        
        start_time = datetime(2026, 2, 4, 8, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2026, 2, 4, 8, 5, 0, tzinfo=timezone.utc)
        
        entries = await client.query_range(
            namespace="demo",
            start_time=start_time,
            end_time=end_time
        )
        
        assert len(entries) == 2
        assert entries[0].namespace == "demo"
        assert entries[0].pod == "test-pod"
        assert entries[0].container == "app"
        assert "ERROR: test message 1" in entries[0].content


@pytest.mark.asyncio
async def test_query_range_timeout():
    """测试 Loki 查询超时"""
    import httpx
    
    client = LokiClient(timeout=1)
    
    with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Timeout")):
        start_time = datetime(2026, 2, 4, 8, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2026, 2, 4, 8, 5, 0, tzinfo=timezone.utc)
        
        with pytest.raises(LokiQueryError, match="超时"):
            await client.query_range(
                namespace="demo",
                start_time=start_time,
                end_time=end_time
            )


@pytest.mark.asyncio
async def test_query_range_http_error():
    """测试 Loki HTTP 错误"""
    import httpx
    
    client = LokiClient()
    
    # 创建一个同步 Mock 响应对象
    class MockResponse:
        status_code = 500
        text = "Internal Server Error"
        
        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "Server error",
                request=AsyncMock(),
                response=self
            )
    
    mock_response = MockResponse()
    
    with patch("httpx.AsyncClient.get", return_value=mock_response):
        start_time = datetime(2026, 2, 4, 8, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2026, 2, 4, 8, 5, 0, tzinfo=timezone.utc)
        
        with pytest.raises(LokiQueryError, match="查询失败"):
            await client.query_range(
                namespace="demo",
                start_time=start_time,
                end_time=end_time
            )


@pytest.mark.asyncio
async def test_parse_response_empty():
    """测试解析空响应"""
    client = LokiClient()
    
    response = {
        "status": "success",
        "data": {
            "result": []
        }
    }
    
    entries = client._parse_response(response)
    
    assert len(entries) == 0


@pytest.mark.asyncio
async def test_parse_response_invalid_status():
    """测试解析错误状态响应"""
    client = LokiClient()
    
    response = {
        "status": "error",
        "error": "query error"
    }
    
    with pytest.raises(LokiQueryError, match="状态异常"):
        client._parse_response(response)


@pytest.mark.asyncio
async def test_log_entry_to_dict():
    """测试 LogEntry 转换为字典"""
    entry = LogEntry(
        timestamp=datetime(2026, 2, 4, 8, 0, 0, tzinfo=timezone.utc),
        content="Test log",
        namespace="demo",
        pod="test-pod",
        container="app"
    )
    
    data = entry.to_dict()
    
    assert data["timestamp"] == "2026-02-04T08:00:00+00:00Z"
    assert data["content"] == "Test log"
    assert data["namespace"] == "demo"
    assert data["pod"] == "test-pod"
    assert data["container"] == "app"
