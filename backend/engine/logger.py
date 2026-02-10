"""
structlog 配置
结构化日志输出
"""
import structlog
import logging
import sys


def configure_logging(log_level: str = "INFO"):
    """
    配置 structlog
    
    Args:
        log_level: 日志级别
    """
    # 配置标准库 logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper())
    )
    
    # 配置 structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str = __name__):
    """
    获取 logger 实例
    
    Args:
        name: logger 名称
    
    Returns:
        structlog logger
    """
    return structlog.get_logger(name)
