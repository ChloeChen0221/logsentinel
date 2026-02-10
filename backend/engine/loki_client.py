"""
Loki HTTP 客户端
用于查询 Loki 日志并解析响应
"""
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional
from config import settings


class LokiQueryError(Exception):
    """Loki 查询错误"""
    pass


class LogEntry:
    """日志条目"""
    def __init__(
        self,
        timestamp: datetime,
        content: str,
        namespace: str,
        pod: str,
        container: Optional[str] = None
    ):
        self.timestamp = timestamp
        self.content = content
        self.namespace = namespace
        self.pod = pod
        self.container = container
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "timestamp": self.timestamp.isoformat() + "Z",
            "content": self.content,
            "namespace": self.namespace,
            "pod": self.pod,
            "container": self.container
        }


class LokiClient:
    """Loki HTTP 客户端"""
    
    def __init__(self, base_url: Optional[str] = None, timeout: int = 5):
        """
        初始化客户端
        
        Args:
            base_url: Loki 服务地址
            timeout: 请求超时时间（秒）
        """
        self.base_url = base_url or settings.LOKI_URL
        self.timeout = timeout
    
    def _build_query(
        self,
        namespace: str,
        labels: Optional[Dict[str, str]] = None,
        keyword: Optional[str] = None
    ) -> str:
        """
        构造 LogQL 查询语句
        
        Args:
            namespace: 命名空间
            labels: 标签选择器
            keyword: 关键词（用于匹配）
        
        Returns:
            LogQL 查询语句
        """
        # 基础查询：命名空间选择器
        query_parts = [f'namespace="{namespace}"']
        
        # 添加标签选择器
        if labels:
            for key, value in labels.items():
                query_parts.append(f'{key}="{value}"')
        
        query = "{" + ", ".join(query_parts) + "}"
        
        # 添加关键词匹配（line filter）
        if keyword:
            query += f' |= "{keyword}"'
        
        return query
    
    async def query_range(
        self,
        namespace: str,
        start_time: datetime,
        end_time: datetime,
        labels: Optional[Dict[str, str]] = None,
        keyword: Optional[str] = None,
        limit: int = 1000
    ) -> List[LogEntry]:
        """
        查询指定时间范围的日志
        
        Args:
            namespace: 命名空间
            start_time: 起始时间
            end_time: 结束时间
            labels: 标签选择器
            keyword: 关键词匹配
            limit: 返回结果限制
        
        Returns:
            日志条目列表
        
        Raises:
            LokiQueryError: 查询失败
        """
        # 构造 LogQL 查询
        query = self._build_query(namespace, labels, keyword)
        
        # 时间戳转换为纳秒
        start_ns = int(start_time.timestamp() * 1e9)
        end_ns = int(end_time.timestamp() * 1e9)
        
        # 构造请求参数
        params = {
            "query": query,
            "start": str(start_ns),
            "end": str(end_ns),
            "limit": str(limit),
            "direction": "forward"
        }
        
        # 发送请求
        url = f"{self.base_url}/loki/api/v1/query_range"
        
        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as e:
            raise LokiQueryError(f"Loki 查询超时: {str(e)}")
        except requests.HTTPError as e:
            raise LokiQueryError(f"Loki 查询失败: {e.response.status_code} - {e.response.text}")
        except Exception as e:
            raise LokiQueryError(f"Loki 查询异常: {str(e)}")
        
        # 解析响应
        return self._parse_response(data)
    
    def _parse_response(self, response: Dict[str, Any]) -> List[LogEntry]:
        """
        解析 Loki 响应
        
        Args:
            response: Loki API 响应
        
        Returns:
            日志条目列表
        """
        entries = []
        
        # 检查响应状态
        if response.get("status") != "success":
            raise LokiQueryError(f"Loki 响应状态异常: {response.get('status')}")
        
        # 提取日志条目
        result_data = response.get("data", {})
        results = result_data.get("result", [])
        
        for result in results:
            stream = result.get("stream", {})
            values = result.get("values", [])
            
            for value in values:
                if len(value) < 2:
                    continue
                
                # 解析时间戳（纳秒 -> datetime）
                timestamp_ns = int(value[0])
                timestamp = datetime.fromtimestamp(timestamp_ns / 1e9)
                
                # 解析日志内容
                content = value[1]
                
                # 创建日志条目
                entry = LogEntry(
                    timestamp=timestamp,
                    content=content,
                    namespace=stream.get("namespace", ""),
                    pod=stream.get("pod", ""),
                    container=stream.get("container")
                )
                entries.append(entry)
        
        return entries
