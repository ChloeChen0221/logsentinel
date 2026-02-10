import React, { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Form,
  Input,
  Select,
  InputNumber,
  Switch,
  Button,
  Card,
  message,
  Space,
} from 'antd'
import { rulesService, type RuleCreate } from '../services/rules'

const { Option } = Select

const RuleForm: React.FC = () => {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const isEdit = !!id

  useEffect(() => {
    if (isEdit) {
      loadRule()
    }
  }, [id])

  const loadRule = async () => {
    if (!id) return
    setLoading(true)
    try {
      const rule = await rulesService.get(Number(id))
      form.setFieldsValue(rule)
    } catch (error) {
      message.error('加载规则失败')
      console.error(error)
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (values: RuleCreate) => {
    setSubmitting(true)
    try {
      if (isEdit && id) {
        await rulesService.update(Number(id), values)
        message.success('规则更新成功')
      } else {
        await rulesService.create(values)
        message.success('规则创建成功')
      }
      navigate('/rules')
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '操作失败'
      message.error(errorMsg)
      console.error(error)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card
      title={isEdit ? '编辑规则' : '创建规则'}
      loading={loading}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        initialValues={{
          enabled: true,
          severity: 'medium',
          match_type: 'contains',
          window_seconds: 0,
          threshold: 1,
          group_by: ['namespace', 'pod'],
          cooldown_seconds: 300,
        }}
        style={{ maxWidth: 800 }}
      >
        <Form.Item
          label="规则名称"
          name="name"
          rules={[
            { required: true, message: '请输入规则名称' },
            { min: 1, max: 255, message: '名称长度为 1-255 个字符' },
          ]}
        >
          <Input placeholder="例如：生产环境错误告警" />
        </Form.Item>

        <Form.Item
          label="严重级别"
          name="severity"
          rules={[{ required: true, message: '请选择严重级别' }]}
        >
          <Select>
            <Option value="low">低 (Low)</Option>
            <Option value="medium">中 (Medium)</Option>
            <Option value="high">高 (High)</Option>
            <Option value="critical">严重 (Critical)</Option>
          </Select>
        </Form.Item>

        <Form.Item
          label="命名空间"
          name="selector_namespace"
          rules={[{ required: true, message: '请输入命名空间' }]}
        >
          <Input placeholder="例如：demo" />
        </Form.Item>

        <Form.Item
          label="匹配类型"
          name="match_type"
          rules={[{ required: true, message: '请选择匹配类型' }]}
        >
          <Select>
            <Option value="contains">关键词包含</Option>
            <Option value="regex">正则表达式（暂不支持）</Option>
          </Select>
        </Form.Item>

        <Form.Item
          label="匹配模式"
          name="match_pattern"
          rules={[{ required: true, message: '请输入匹配模式' }]}
        >
          <Input placeholder="例如：ERROR" />
        </Form.Item>

        <Form.Item
          label="时间窗口（秒）"
          name="window_seconds"
          tooltip="设置为 0 表示关键词规则，大于 0 表示窗口阈值规则"
          rules={[{ required: true, message: '请输入时间窗口' }]}
        >
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item
          label="阈值"
          name="threshold"
          tooltip="窗口内命中次数达到此值时触发告警"
          rules={[{ required: true, message: '请输入阈值' }]}
        >
          <InputNumber min={1} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item
          label="分组维度"
          name="group_by"
          rules={[{ required: true, message: '请选择分组维度' }]}
        >
          <Select mode="multiple" placeholder="选择分组维度">
            <Option value="namespace">命名空间</Option>
            <Option value="pod">Pod</Option>
            <Option value="container">容器</Option>
          </Select>
        </Form.Item>

        <Form.Item
          label="冷却时间（秒）"
          name="cooldown_seconds"
          tooltip="同一告警在冷却期内不会重复发送通知"
          rules={[{ required: true, message: '请输入冷却时间' }]}
        >
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item
          label="启用状态"
          name="enabled"
          valuePropName="checked"
        >
          <Switch checkedChildren="启用" unCheckedChildren="停用" />
        </Form.Item>

        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={submitting}>
              {isEdit ? '更新' : '创建'}
            </Button>
            <Button onClick={() => navigate('/rules')}>
              取消
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  )
}

export default RuleForm
