from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import re


class RuleStepSchema(BaseModel):
    """规则步骤 Schema"""
    step_order: int = Field(..., ge=0, description="步骤序号（从 0 开始）")
    match_type: str = Field(..., description="匹配类型")
    match_pattern: str = Field(..., min_length=1, description="匹配模式")
    window_seconds: int = Field(60, ge=1, description="该步骤超时窗口（秒）")
    threshold: int = Field(1, ge=1, description="命中次数阈值")

    @field_validator("match_type")
    @classmethod
    def validate_match_type(cls, v: str) -> str:
        allowed = ["contains", "regex"]
        if v not in allowed:
            raise ValueError(f"match_type 必须是 {allowed} 之一")
        return v

    model_config = {"from_attributes": True}


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
    rule_type: str = Field("keyword", description="规则类型: keyword / threshold / sequence")
    correlation_type: Optional[str] = Field(None, description="关联类型: sequence / negative（仅序列规则有效）")
    
    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = ["low", "medium", "high", "critical"]
        if v not in allowed:
            raise ValueError(f"severity 必须是 {allowed} 之一")
        return v
    
    @field_validator("match_type")
    @classmethod
    def validate_match_type(cls, v: str) -> str:
        allowed = ["contains", "regex"]
        if v not in allowed:
            raise ValueError(f"match_type 必须是 {allowed} 之一")
        return v
    
    @field_validator("group_by")
    @classmethod
    def validate_group_by(cls, v: List[str]) -> List[str]:
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
        if not v.strip():
            raise ValueError("match_pattern 不能为空")
        return v

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v: str) -> str:
        allowed = ["keyword", "threshold", "sequence"]
        if v not in allowed:
            raise ValueError(f"rule_type 必须是 {allowed} 之一")
        return v

    @field_validator("correlation_type")
    @classmethod
    def validate_correlation_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            allowed = ["sequence", "negative"]
            if v not in allowed:
                raise ValueError(f"correlation_type 必须是 {allowed} 之一")
        return v


class RuleCreate(RuleBase):
    """创建规则请求"""
    enabled: bool = Field(True, description="启用状态")
    steps: Optional[List[RuleStepSchema]] = Field(None, description="序列规则步骤（rule_type=sequence 时必填）")
    
    @field_validator("match_pattern")
    @classmethod
    def validate_regex_pattern(cls, v: str, info) -> str:
        if info.data.get("match_type") == "regex":
            try:
                re.compile(v)
            except re.error as e:
                raise ValueError(f"match_pattern 正则表达式不合法: {str(e)}")
        return v

    @model_validator(mode="after")
    def validate_sequence_rule(self) -> "RuleCreate":
        if self.rule_type == "sequence":
            if not self.steps or len(self.steps) < 2:
                raise ValueError("序列规则至少需要2个步骤")
            if self.correlation_type is None:
                raise ValueError("序列规则必须指定 correlation_type")
        return self


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
    rule_type: Optional[str] = None
    correlation_type: Optional[str] = None
    steps: Optional[List[RuleStepSchema]] = None
    
    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            allowed = ["low", "medium", "high", "critical"]
            if v not in allowed:
                raise ValueError(f"severity 必须是 {allowed} 之一")
        return v
    
    @field_validator("match_type")
    @classmethod
    def validate_match_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            allowed = ["contains", "regex"]
            if v not in allowed:
                raise ValueError(f"match_type 必须是 {allowed} 之一")
        return v
    
    @field_validator("group_by")
    @classmethod
    def validate_group_by(cls, v: Optional[List[str]]) -> Optional[List[str]]:
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
    steps: List[RuleStepSchema] = Field(default_factory=list)
    
    model_config = {"from_attributes": True}


class SequenceStateResponse(BaseModel):
    """序列状态响应"""
    id: int
    rule_id: int
    current_step: int
    step_timestamps: List[Optional[str]]
    started_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

