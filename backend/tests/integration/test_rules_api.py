"""
规则 API 集成测试
"""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_rule(client: AsyncClient):
    """测试创建规则（happy path）"""
    rule_data = {
        "name": "测试规则",
        "enabled": True,
        "severity": "high",
        "selector_namespace": "demo",
        "selector_labels": None,
        "match_type": "contains",
        "match_pattern": "ERROR",
        "window_seconds": 0,
        "threshold": 1,
        "group_by": ["namespace", "pod"],
        "cooldown_seconds": 300
    }
    
    response = await client.post("/api/rules", json=rule_data)
    
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "测试规则"
    assert data["severity"] == "high"
    assert data["enabled"] is True
    assert "id" in data


@pytest.mark.asyncio
async def test_get_rules_empty(client: AsyncClient):
    """测试查询空规则列表"""
    response = await client.get("/api/rules")
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


@pytest.mark.asyncio
async def test_get_rules(client: AsyncClient):
    """测试查询规则列表"""
    # 先创建一条规则
    rule_data = {
        "name": "测试规则",
        "enabled": True,
        "severity": "high",
        "selector_namespace": "demo",
        "match_type": "contains",
        "match_pattern": "ERROR",
        "group_by": ["namespace", "pod"]
    }
    await client.post("/api/rules", json=rule_data)
    
    # 查询列表
    response = await client.get("/api/rules")
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "测试规则"


@pytest.mark.asyncio
async def test_get_rule_by_id(client: AsyncClient):
    """测试查询规则详情"""
    # 创建规则
    rule_data = {
        "name": "测试规则",
        "enabled": True,
        "severity": "high",
        "selector_namespace": "demo",
        "match_type": "contains",
        "match_pattern": "ERROR",
        "group_by": ["namespace", "pod"]
    }
    create_response = await client.post("/api/rules", json=rule_data)
    rule_id = create_response.json()["id"]
    
    # 查询详情
    response = await client.get(f"/api/rules/{rule_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == rule_id
    assert data["name"] == "测试规则"


@pytest.mark.asyncio
async def test_get_rule_not_found(client: AsyncClient):
    """测试查询不存在的规则"""
    response = await client.get("/api/rules/999")
    
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_update_rule(client: AsyncClient):
    """测试更新规则"""
    # 创建规则
    rule_data = {
        "name": "测试规则",
        "enabled": True,
        "severity": "high",
        "selector_namespace": "demo",
        "match_type": "contains",
        "match_pattern": "ERROR",
        "group_by": ["namespace", "pod"]
    }
    create_response = await client.post("/api/rules", json=rule_data)
    rule_id = create_response.json()["id"]
    
    # 更新规则
    update_data = {
        "name": "更新后的规则",
        "severity": "critical"
    }
    response = await client.put(f"/api/rules/{rule_id}", json=update_data)
    
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "更新后的规则"
    assert data["severity"] == "critical"


@pytest.mark.asyncio
async def test_enable_rule(client: AsyncClient):
    """测试启用规则"""
    # 创建停用的规则
    rule_data = {
        "name": "测试规则",
        "enabled": False,
        "severity": "high",
        "selector_namespace": "demo",
        "match_type": "contains",
        "match_pattern": "ERROR",
        "group_by": ["namespace", "pod"]
    }
    create_response = await client.post("/api/rules", json=rule_data)
    rule_id = create_response.json()["id"]
    
    # 启用规则
    response = await client.patch(f"/api/rules/{rule_id}/enable")
    
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True


@pytest.mark.asyncio
async def test_disable_rule(client: AsyncClient):
    """测试停用规则"""
    # 创建启用的规则
    rule_data = {
        "name": "测试规则",
        "enabled": True,
        "severity": "high",
        "selector_namespace": "demo",
        "match_type": "contains",
        "match_pattern": "ERROR",
        "group_by": ["namespace", "pod"]
    }
    create_response = await client.post("/api/rules", json=rule_data)
    rule_id = create_response.json()["id"]
    
    # 停用规则
    response = await client.patch(f"/api/rules/{rule_id}/disable")
    
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is False


@pytest.mark.asyncio
async def test_delete_rule(client: AsyncClient):
    """测试删除规则"""
    # 创建规则
    rule_data = {
        "name": "测试规则",
        "enabled": True,
        "severity": "high",
        "selector_namespace": "demo",
        "match_type": "contains",
        "match_pattern": "ERROR",
        "group_by": ["namespace", "pod"]
    }
    create_response = await client.post("/api/rules", json=rule_data)
    rule_id = create_response.json()["id"]
    
    # 删除规则
    response = await client.delete(f"/api/rules/{rule_id}")
    
    assert response.status_code == 204
    
    # 验证规则已删除
    get_response = await client.get(f"/api/rules/{rule_id}")
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_create_rule_invalid_severity(client: AsyncClient):
    """测试创建规则（无效的严重级别）"""
    rule_data = {
        "name": "测试规则",
        "enabled": True,
        "severity": "invalid",
        "selector_namespace": "demo",
        "match_type": "contains",
        "match_pattern": "ERROR",
        "group_by": ["namespace", "pod"]
    }
    
    response = await client.post("/api/rules", json=rule_data)
    
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_rule_invalid_regex(client: AsyncClient):
    """测试创建规则（无效的正则表达式）"""
    rule_data = {
        "name": "测试规则",
        "enabled": True,
        "severity": "high",
        "selector_namespace": "demo",
        "match_type": "regex",
        "match_pattern": "[invalid",
        "group_by": ["namespace", "pod"]
    }
    
    response = await client.post("/api/rules", json=rule_data)
    
    assert response.status_code == 422
