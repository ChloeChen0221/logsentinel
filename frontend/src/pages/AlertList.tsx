import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Table,
  Tag,
  Card,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { alertsService, type Alert } from '../services/alerts'
import dayjs from 'dayjs'

const AlertList: React.FC = () => {
  const navigate = useNavigate()
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [loading, setLoading] = useState(false)
  const [pagination, setPagination] = useState({
    current: 1,
    pageSize: 20,
    total: 0,
  })

  const loadAlerts = async (page = 1, pageSize = 20) => {
    setLoading(true)
    try {
      const response = await alertsService.list({
        page,
        page_size: pageSize,
      })
      setAlerts(response.items)
      setPagination({
        current: response.page,
        pageSize: response.page_size,
        total: response.total,
      })
    } catch (error) {
      message.error('加载告警列表失败')
      console.error(error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAlerts()
  }, [])

  const getSeverityColor = (severity: string) => {
    const colors: Record<string, string> = {
      low: 'default',
      medium: 'processing',
      high: 'warning',
      critical: 'error',
    }
    return colors[severity] || 'default'
  }

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      active: 'error',
      resolved: 'success',
    }
    return colors[status] || 'default'
  }

  const columns: ColumnsType<Alert> = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 80,
    },
    {
      title: '规则 ID',
      dataIndex: 'rule_id',
      key: 'rule_id',
      width: 100,
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
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status) => (
        <Tag color={getStatusColor(status)}>
          {status.toUpperCase()}
        </Tag>
      ),
    },
    {
      title: '命中次数',
      dataIndex: 'hit_count',
      key: 'hit_count',
      width: 100,
    },
    {
      title: '分组',
      dataIndex: 'group_by',
      key: 'group_by',
      width: 200,
      render: (groupBy: Record<string, string>) => (
        <div>
          {Object.entries(groupBy).map(([key, value]) => (
            <div key={key}>
              <Tag>{key}: {value}</Tag>
            </div>
          ))}
        </div>
      ),
    },
    {
      title: '首次触发',
      dataIndex: 'first_seen',
      key: 'first_seen',
      width: 180,
      render: (date) => dayjs(date).format('YYYY-MM-DD HH:mm:ss'),
    },
    {
      title: '最后触发',
      dataIndex: 'last_seen',
      key: 'last_seen',
      width: 180,
      render: (date) => dayjs(date).format('YYYY-MM-DD HH:mm:ss'),
      sorter: true,
      defaultSortOrder: 'descend',
    },
  ]

  return (
    <Card title="告警列表">
      <Table
        columns={columns}
        dataSource={alerts}
        rowKey="id"
        loading={loading}
        pagination={{
          ...pagination,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
          onChange: (page, pageSize) => {
            loadAlerts(page, pageSize)
          },
        }}
        onRow={(record) => ({
          onClick: () => navigate(`/alerts/${record.id}`),
          style: { cursor: 'pointer' },
        })}
      />
    </Card>
  )
}

export default AlertList
