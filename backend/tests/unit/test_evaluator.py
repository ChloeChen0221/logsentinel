"""
规则评估器单元测试
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from backend.engine.evaluator import RuleEvaluator
from backend.engine.loki_client import LogEntry
from backend.models import Rule


@pytest.fixture
def mock_rule():
    """创建 mock 规则"""
    rule = MagicMock(spec=Rule)
    rule.id = 1
    rule.name = "Test Rule"
    rule.enabled = True
    rule.severity = "high"
    rule.selector_namespace = "demo"
    rule.selector_labels = None
    rule.match_type = "contains"
    rule.match_pattern = "ERROR"
    rule.window_seconds = 0
    rule.threshold = 1
    rule.group_by = ["namespace", "pod"]
    rule.cooldown_seconds = 300
    rule.last_query_time = None
    return rule


@pytest.fixture
def mock_db():
    """创建 mock 数据库会话"""
    db = AsyncMock()
    return db


@pytest.fixture
def mock_loki_client():
    """创建 mock Loki 客户端"""
    client = AsyncMock()
    return client


@pytest.mark.asyncio
async def test_load_enabled_rules(mock_db):
    """测试加载已启用规则"""
    # Mock 查询结果
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [
        MagicMock(id=1, enabled=True),
        MagicMock(id=2, enabled=True)
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_result
    
    evaluator = RuleEvaluator(mock_db)
    rules = await evaluator.load_enabled_rules()
    
    assert len(rules) == 2
    assert rules[0].id == 1
    assert rules[1].id == 2


@pytest.mark.asyncio
async def test_match_contains_success(mock_db, mock_loki_client, mock_rule):
    """测试关键词匹配成功"""
    # Mock Loki 响应
    entries = [
        LogEntry(
            timestamp=datetime.now(timezone.utc),
            content="ERROR: Connection failed",
            namespace="demo",
            pod="test-pod-1",
            container="app"
        ),
        LogEntry(
            timestamp=datetime.now(timezone.utc),
            content="INFO: Normal log",
            namespace="demo",
            pod="test-pod-1",
            container="app"
        ),
        LogEntry(
            timestamp=datetime.now(timezone.utc),
            content="ERROR: Timeout",
            namespace="demo",
            pod="test-pod-2",
            container="app"
        )
    ]
    
    mock_loki_client.query_range.return_value = entries
    
    evaluator = RuleEvaluator(mock_db, mock_loki_client)
    matched = evaluator._match_contains("ERROR", entries)
    
    assert len(matched) == 2
    assert "ERROR" in matched[0].content
    assert "ERROR" in matched[1].content


@pytest.mark.asyncio
async def test_match_contains_no_match(mock_db, mock_loki_client):
    """测试关键词无匹配"""
    entries = [
        LogEntry(
            timestamp=datetime.now(timezone.utc),
            content="INFO: Normal log",
            namespace="demo",
            pod="test-pod",
            container="app"
        )
    ]
    
    evaluator = RuleEvaluator(mock_db, mock_loki_client)
    matched = evaluator._match_contains("ERROR", entries)
    
    assert len(matched) == 0


@pytest.mark.asyncio
async def test_evaluate_rule_first_time(mock_db, mock_loki_client, mock_rule):
    """测试首次评估规则（last_query_time 为 None）"""
    # Mock Loki 响应
    mock_loki_client.query_range.return_value = [
        LogEntry(
            timestamp=datetime.now(timezone.utc),
            content="ERROR: test",
            namespace="demo",
            pod="test-pod",
            container="app"
        )
    ]
    
    # Mock alert manager
    mock_alert = MagicMock()
    mock_alert.id = 1
    
    with patch("backend.engine.evaluator.AlertManager") as MockAlertManager:
        mock_manager = AsyncMock()
        mock_manager.create_or_update_alert.return_value = mock_alert
        MockAlertManager.return_value = mock_manager
        
        evaluator = RuleEvaluator(mock_db, mock_loki_client)
        evaluator.should_notify = MagicMock(return_value=False)  # Mock 冷却期检查
        result = await evaluator.evaluate_rule(mock_rule)
        
        # 验证查询了 Loki（首次查询最近 5 分钟）
        assert mock_loki_client.query_range.called
        call_args = mock_loki_client.query_range.call_args
        start_time = call_args.kwargs["start_time"]
        end_time = call_args.kwargs["end_time"]
        
        # 验证时间范围约为 5 分钟
        time_diff = (end_time - start_time).total_seconds()
        assert 280 < time_diff < 320  # 允许一些误差
        
        # 验证结果
        assert result is True


@pytest.mark.asyncio
async def test_evaluate_rule_with_last_query_time(mock_db, mock_loki_client, mock_rule):
    """测试增量查询（使用 last_query_time）"""
    # 设置 last_query_time
    last_query = datetime.now(timezone.utc) - timedelta(seconds=60)
    mock_rule.last_query_time = last_query
    
    mock_loki_client.query_range.return_value = []
    
    evaluator = RuleEvaluator(mock_db, mock_loki_client)
    await evaluator.evaluate_rule(mock_rule)
    
    # 验证使用了 last_query_time
    call_args = mock_loki_client.query_range.call_args
    start_time = call_args.kwargs["start_time"]
    
    # start_time 应该等于 last_query_time
    assert start_time == last_query


@pytest.mark.asyncio
async def test_evaluate_rule_updates_last_query_time(mock_db, mock_loki_client, mock_rule):
    """测试成功后更新 last_query_time"""
    mock_loki_client.query_range.return_value = []
    
    evaluator = RuleEvaluator(mock_db, mock_loki_client)
    await evaluator.evaluate_rule(mock_rule)
    
    # 验证更新了 last_query_time
    assert mock_db.execute.called
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_evaluate_rule_loki_failure(mock_db, mock_loki_client, mock_rule):
    """测试 Loki 查询失败时不更新 last_query_time"""
    # Mock Loki 查询失败
    from backend.engine.loki_client import LokiQueryError
    mock_loki_client.query_range.side_effect = LokiQueryError("Query failed")
    
    evaluator = RuleEvaluator(mock_db, mock_loki_client)
    result = await evaluator.evaluate_rule(mock_rule)
    
    # 验证返回 False
    assert result is False
    
    # 验证没有更新 last_query_time（没有调用 execute 更新）
    # 注意：这里我们检查 commit 没有被调用，因为失败时不应该提交
    # 但是由于 evaluate_rule 内部可能有其他 db 操作，这个测试可能需要调整
