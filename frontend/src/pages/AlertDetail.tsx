import React, { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Card,
  Descriptions,
  Tag,
  Button,
  message,
  Space,
  Typography,
} from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { alertsService, type Alert } from '../services/alerts'
import dayjs from 'dayjs'

const { Text, Paragraph } = Typography

const AlertDetail: React.FC = () => {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [alert, setAlert] = useState<Alert | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (id) {
      loadAlert()
    }
  }, [id])

  const loadAlert = async () => {
    if (!id) return
    setLoading(true)
    try {
      const data = await alertsService.get(Number(id))
      setAlert(data)
    } catch (error) {
      message.error('加载告警详情失败')
      console.error(error)
    } finally {
      setLoading(false)
    }
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

  const getStatusColor = (status: string) => {
    const colors: Record<string, string> = {
      active: 'error',
      resolved: 'success',
    }
    return colors[status] || 'default'
  }

  if (!alert) {
    return (
      <Card loading={loading}>
        <p>加载中...</p>
      </Card>
    )
  }

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Card
        title={
          <Space>
            <Button
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate('/alerts')}
            >
              返回列表
            </Button>
            <span>告警详情 #{alert.id}</span>
          </Space>
        }
        loading={loading}
      >
        <Descriptions bordered column={2}>
          <Descriptions.Item label="告警 ID">{alert.id}</Descriptions.Item>
          <Descriptions.Item label="规则 ID">{alert.rule_id}</Descriptions.Item>
          
          <Descriptions.Item label="严重级别">
            <Tag color={getSeverityColor(alert.severity)}>
              {alert.severity.toUpperCase()}
            </Tag>
          </Descriptions.Item>
          
          <Descriptions.Item label="状态">
            <Tag color={getStatusColor(alert.status)}>
              {alert.status.toUpperCase()}
            </Tag>
          </Descriptions.Item>
          
          <Descriptions.Item label="首次触发时间">
            {dayjs(alert.first_seen).format('YYYY-MM-DD HH:mm:ss')}
          </Descriptions.Item>
          
          <Descriptions.Item label="最后触发时间">
            {dayjs(alert.last_seen).format('YYYY-MM-DD HH:mm:ss')}
          </Descriptions.Item>
          
          <Descriptions.Item label="累计命中次数">
            <Text strong>{alert.hit_count}</Text>
          </Descriptions.Item>
          
          <Descriptions.Item label="最后通知时间">
            {alert.last_notified_at
              ? dayjs(alert.last_notified_at).format('YYYY-MM-DD HH:mm:ss')
              : '未通知'}
          </Descriptions.Item>
          
          <Descriptions.Item label="分组维度" span={2}>
            <Space wrap>
              {Object.entries(alert.group_by).map(([key, value]) => (
                <Tag key={key}>
                  {key}: <Text code>{value}</Text>
                </Tag>
              ))}
            </Space>
          </Descriptions.Item>
          
          <Descriptions.Item label="指纹" span={2}>
            <Text code copyable>{alert.fingerprint}</Text>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="样例日志">
        <Descriptions bordered column={1}>
          <Descriptions.Item label="时间戳">
            {dayjs(alert.sample_log.timestamp).format('YYYY-MM-DD HH:mm:ss.SSS')}
          </Descriptions.Item>
          
          <Descriptions.Item label="命名空间">
            <Tag>{alert.sample_log.namespace}</Tag>
          </Descriptions.Item>
          
          <Descriptions.Item label="Pod">
            <Tag color="blue">{alert.sample_log.pod}</Tag>
          </Descriptions.Item>
          
          {alert.sample_log.container && (
            <Descriptions.Item label="容器">
              <Tag color="cyan">{alert.sample_log.container}</Tag>
            </Descriptions.Item>
          )}
          
          <Descriptions.Item label="日志内容">
            <Paragraph
              code
              copyable
              style={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-all',
                marginBottom: 0,
                padding: '12px',
                backgroundColor: '#f5f5f5',
              }}
            >
              {alert.sample_log.content}
            </Paragraph>
          </Descriptions.Item>
        </Descriptions>
      </Card>
    </Space>
  )
}

export default AlertDetail
