import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table,
  Button,
  Space,
  Tag,
  Switch,
  Modal,
  message,
  Card,
} from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { rulesService, type Rule } from '../services/rules'
import dayjs from 'dayjs'

const RuleList: React.FC = () => {
  const navigate = useNavigate()
  const [rules, setRules] = useState<Rule[]>([])
  const [loading, setLoading] = useState(false)

  const loadRules = async () => {
    setLoading(true)
    try {
      const data = await rulesService.list()
      setRules(data)
    } catch (error) {
      message.error('加载规则列表失败')
      console.error(error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRules()
  }, [])

  const handleToggleEnabled = async (rule: Rule) => {
    try {
      if (rule.enabled) {
        await rulesService.disable(rule.id)
        message.success('规则已停用')
      } else {
        await rulesService.enable(rule.id)
        message.success('规则已启用')
      }
      loadRules()
    } catch (error) {
      message.error('操作失败')
      console.error(error)
    }
  }

  const handleDelete = (rule: Rule) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除规则"${rule.name}"吗？此操作不可恢复。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await rulesService.delete(rule.id)
          message.success('规则已删除')
          loadRules()
        } catch (error) {
          message.error('删除失败')
          console.error(error)
        }
      },
    })
  }

  const getSeverityColor = (severity: string) => {
    const colors: Record<string, string> = {
      low: 'default',
      medium: 'processing',
      high: 'warning',
      critical: 'error',
    }
    return colors[severity] || 'default'
  }

  const getRuleType = (rule: Rule) => {
    if (rule.window_seconds > 0) {
      return '窗口阈值'
    }
    return '关键词匹配'
  }

  const columns: ColumnsType<Rule> = [
    {
      title: '规则名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
    },
    {
      title: '类型',
      key: 'type',
      width: 120,
      render: (_, record) => getRuleType(record),
    },
    {
      title: '严重级别',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
      render: (severity) => (
        <Tag color={getSeverityColor(severity)}>
          {severity.toUpperCase()}
        </Tag>
      ),
    },
    {
      title: '命名空间',
      dataIndex: 'selector_namespace',
      key: 'selector_namespace',
      width: 150,
    },
    {
      title: '匹配模式',
      dataIndex: 'match_pattern',
      key: 'match_pattern',
      width: 200,
      ellipsis: true,
    },
    {
      title: '启用状态',
      dataIndex: 'enabled',
      key: 'enabled',
      width: 100,
      render: (enabled, record) => (
        <Switch
          checked={enabled}
          onChange={() => handleToggleEnabled(record)}
        />
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (date) => dayjs(date).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            icon={<EditOutlined />}
            onClick={() => navigate(`/rules/${record.id}/edit`)}
          >
            编辑
          </Button>
          <Button
            type="link"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="规则管理"
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => navigate('/rules/new')}
        >
          新建规则
        </Button>
      }
    >
      <Table
        columns={columns}
        dataSource={rules}
        rowKey="id"
        loading={loading}
        pagination={{
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
        }}
      />
    </Card>
  )
}

export default RuleList
