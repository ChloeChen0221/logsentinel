"""
SQLAlchemy Base 类
所有模型都继承自此类
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass
