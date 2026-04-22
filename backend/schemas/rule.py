from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import re


# 允许的通知渠道类型（当前仅支持 wecom + console）
_ALLOWED_CHANNEL_TYPES = {"wecom", "console"}
_WECOM_WEBHOOK_PREFIX = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
# 中国大陆手机号：11 位，1 开头，第二位 3-9
_PHONE_REGEX = re.compile(r"^1[3-9]\d{9}$")


class NotifyChannelConfig(BaseModel):
    """通知渠道配置（嵌入在 rule.notify_config 数组中的单元）"""
    type: str = Field(..., description="渠道类型：wecom / console")
    name: str = Field(..., min_length=1, max_length=50, description="渠道显示名")
    webhook_url: Optional[str] = Field(None, description="wecom 类型必填")
    mentioned_mobile_list: Optional[List[str]] = Field(
        default_factory=list, description="wecom 可选，@手机号列表；`@all` 表示所有人"
    )

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in _ALLOWED_CHANNEL_TYPES:
            raise ValueError(f"channel type 必须是 {sorted(_ALLOWED_CHANNEL_TYPES)} 之一")
        return v

    @field_validator("mentioned_mobile_list")
    @classmethod
    def validate_mobiles(cls, v: Optional[List[str]]) -> List[str]:
        v = v or []
        for m in v:
            if m == "@all":
                continue
            if not _PHONE_REGEX.match(m):
                raise ValueError(f"非法手机号格式: {m}")
        return v

    @model_validator(mode="after")
    def validate_wecom_fields(self) -> "NotifyChannelConfig":
        if self.type == "wecom":
            if not self.webhook_url:
                raise ValueError("wecom 渠道必须提供 webhook_url")
            if not self.webhook_url.startswith(_WECOM_WEBHOOK_PREFIX):
                raise ValueError(f"wecom webhook_url 必须以 {_WECOM_WEBHOOK_PREFIX} 开头")
            if "key=" not in self.webhook_url:
                raise ValueError("wecom webhook_url 必须包含 key 参数")
        return self

    model_config = {"from_attributes": True}


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
    notify_config: List[NotifyChannelConfig] = Field(
        default_factory=list,
        description="通知渠道列表；为空则 fallback 到 console",
    )
    
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
    notify_config: Optional[List[NotifyChannelConfig]] = None
    
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

