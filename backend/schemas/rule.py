"""
Rule Pydantic Schemas
规则管理 API 的请求/响应模型
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import re


class RuleBase(BaseModel):
    """规则基础模型"""
    name: str = Field(..., min_length=1, max_length=255, description="规则名称")
    severity: str = Field(..., description="严重级别")
    selector_namespace: str = Field(..., min_length=1, description="命名空间选择器")
    selector_labels: Optional[Dict[str, str]] = Field(None, description="标签选择器")
    match_type: str = Field(..., description="匹配类型")
    match_pattern: str = Field(..., min_length=1, description="匹配模式")
    window_seconds: int = Field(0, ge=0, description="时间窗口（秒）")
    threshold: int = Field(1, ge=1, description="阈值")
    group_by: List[str] = Field(..., description="分组维度")
    cooldown_seconds: int = Field(300, ge=0, description="冷却时间（秒）")
    
    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        """验证严重级别"""
        allowed = ["low", "medium", "high", "critical"]
        if v not in allowed:
            raise ValueError(f"severity 必须是 {allowed} 之一")
        return v
    
    @field_validator("match_type")
    @classmethod
    def validate_match_type(cls, v: str) -> str:
        """验证匹配类型"""
        allowed = ["contains", "regex"]
        if v not in allowed:
            raise ValueError(f"match_type 必须是 {allowed} 之一")
        return v
    
    @field_validator("group_by")
    @classmethod
    def validate_group_by(cls, v: List[str]) -> List[str]:
        """验证分组维度"""
        if not v:
            raise ValueError("group_by 不能为空")
        allowed = ["namespace", "pod", "container"]
        for item in v:
            if item not in allowed:
                raise ValueError(f"group_by 元素必须是 {allowed} 之一")
        return v
    
    @field_validator("match_pattern")
    @classmethod
    def validate_match_pattern(cls, v: str, info) -> str:
        """验证匹配模式（如果是 regex 类型，检查正则表达式合法性）"""
        # 注意：这里无法直接访问 match_type，需要在模型级别验证
        # 暂时只检查非空
        if not v.strip():
            raise ValueError("match_pattern 不能为空")
        return v


class RuleCreate(RuleBase):
    """创建规则请求"""
    enabled: bool = Field(True, description="启用状态")
    
    @field_validator("match_pattern")
    @classmethod
    def validate_regex_pattern(cls, v: str, info) -> str:
        """如果是 regex 类型，验证正则表达式合法性"""
        # 获取 match_type 字段值
        if info.data.get("match_type") == "regex":
            try:
                re.compile(v)
            except re.error as e:
                raise ValueError(f"match_pattern 正则表达式不合法: {str(e)}")
        return v


class RuleUpdate(BaseModel):
    """更新规则请求（所有字段可选）"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    enabled: Optional[bool] = None
    severity: Optional[str] = None
    selector_namespace: Optional[str] = Field(None, min_length=1)
    selector_labels: Optional[Dict[str, str]] = None
    match_type: Optional[str] = None
    match_pattern: Optional[str] = Field(None, min_length=1)
    window_seconds: Optional[int] = Field(None, ge=0)
    threshold: Optional[int] = Field(None, ge=1)
    group_by: Optional[List[str]] = None
    cooldown_seconds: Optional[int] = Field(None, ge=0)
    
    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: Optional[str]) -> Optional[str]:
        """验证严重级别"""
        if v is not None:
            allowed = ["low", "medium", "high", "critical"]
            if v not in allowed:
                raise ValueError(f"severity 必须是 {allowed} 之一")
        return v
    
    @field_validator("match_type")
    @classmethod
    def validate_match_type(cls, v: Optional[str]) -> Optional[str]:
        """验证匹配类型"""
        if v is not None:
            allowed = ["contains", "regex"]
            if v not in allowed:
                raise ValueError(f"match_type 必须是 {allowed} 之一")
        return v
    
    @field_validator("group_by")
    @classmethod
    def validate_group_by(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """验证分组维度"""
        if v is not None:
            if not v:
                raise ValueError("group_by 不能为空")
            allowed = ["namespace", "pod", "container"]
            for item in v:
                if item not in allowed:
                    raise ValueError(f"group_by 元素必须是 {allowed} 之一")
        return v


class RuleResponse(RuleBase):
    """规则响应"""
    id: int
    enabled: bool
    last_query_time: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = {"from_attributes": True}
