"""
告警管理器单元测试
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from backend.engine.alert_manager import AlertManager
from backend.engine.loki_client import LogEntry


@pytest.fixture
def mock_db():
    """创建 mock 数据库会话"""
    db = AsyncMock()
    return db


@pytest.fixture
def sample_log_entry():
    """创建示例日志条目"""
    return LogEntry(
        timestamp=datetime.now(timezone.utc),
        content="ERROR: test message",
        namespace="demo",
        pod="test-pod-123",
        container="app"
    )


def test_generate_fingerprint():
    """测试指纹生成"""
    manager = AlertManager(AsyncMock())
    
    # 相同的输入应该生成相同的指纹
    fp1 = manager.generate_fingerprint(1, {"namespace": "demo", "pod": "pod-1"})
    fp2 = manager.generate_fingerprint(1, {"namespace": "demo", "pod": "pod-1"})
    assert fp1 == fp2
    
    # 不同的 rule_id 应该生成不同的指纹
    fp3 = manager.generate_fingerprint(2, {"namespace": "demo", "pod": "pod-1"})
    assert fp1 != fp3
    
    # 不同的分组维度值应该生成不同的指纹
    fp4 = manager.generate_fingerprint(1, {"namespace": "demo", "pod": "pod-2"})
    assert fp1 != fp4
    
    # 指纹应该是 64 字符的十六进制字符串（SHA256）
    assert len(fp1) == 64
    assert all(c in '0123456789abcdef' for c in fp1)


def test_generate_fingerprint_order_independent():
    """测试指纹生成与字段顺序无关"""
    manager = AlertManager(AsyncMock())
    
    # 不同的字段顺序应该生成相同的指纹
    fp1 = manager.generate_fingerprint(1, {"namespace": "demo", "pod": "pod-1"})
    fp2 = manager.generate_fingerprint(1, {"pod": "pod-1", "namespace": "demo"})
    assert fp1 == fp2


def test_extract_group_by_values(sample_log_entry):
    """测试提取分组维度值"""
    manager = AlertManager(AsyncMock())
    
    # 提取 namespace 和 pod
    values = manager.extract_group_by_values(
        sample_log_entry,
        ["namespace", "pod"]
    )
    assert values == {"namespace": "demo", "pod": "test-pod-123"}
    
    # 提取所有维度
    values = manager.extract_group_by_values(
        sample_log_entry,
        ["namespace", "pod", "container"]
    )
    assert values == {
        "namespace": "demo",
        "pod": "test-pod-123",
        "container": "app"
    }
    
    # 只提取 namespace
    values = manager.extract_group_by_values(
        sample_log_entry,
        ["namespace"]
    )
    assert values == {"namespace": "demo"}


@pytest.mark.asyncio
async def test_create_new_alert(mock_db, sample_log_entry):
    """测试创建新告警"""
    # Mock 查询结果：不存在现有告警
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result
    
    # Mock 规则
    mock_rule = MagicMock()
    mock_rule.id = 1
    mock_rule.severity = "high"
    mock_rule.group_by = ["namespace", "pod"]
    
    manager = AlertManager(mock_db)
    alert = await manager.create_or_update_alert(mock_rule, [sample_log_entry])
    
    # 验证创建了新告警
    assert alert is not None
    assert mock_db.add.called
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_update_existing_alert(mock_db, sample_log_entry):
    """测试更新现有告警"""
    # Mock 查询结果：存在现有告警
    existing_alert = MagicMock()
    existing_alert.id = 1
    existing_alert.hit_count = 5
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_alert
    mock_db.execute.return_value = mock_result
    
    # Mock 规则
    mock_rule = MagicMock()
    mock_rule.id = 1
    mock_rule.severity = "high"
    mock_rule.group_by = ["namespace", "pod"]
    
    manager = AlertManager(mock_db)
    alert = await manager.create_or_update_alert(mock_rule, [sample_log_entry, sample_log_entry])
    
    # 验证更新了告警
    assert alert is not None
    assert existing_alert.hit_count == 7  # 5 + 2
    assert mock_db.commit.called


@pytest.mark.asyncio
async def test_no_alert_for_empty_entries(mock_db):
    """测试空日志列表不创建告警"""
    mock_rule = MagicMock()
    mock_rule.id = 1
    mock_rule.severity = "high"
    mock_rule.group_by = ["namespace", "pod"]
    
    manager = AlertManager(mock_db)
    alert = await manager.create_or_update_alert(mock_rule, [])
    
    # 应该返回 None
    assert alert is None
    assert not mock_db.add.called
    assert not mock_db.commit.called
