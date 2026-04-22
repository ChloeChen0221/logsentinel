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
  Divider,
  Alert,
} from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'
import { rulesService, type RuleCreate, type RuleStep } from '../services/rules'

const { Option } = Select

const CORRELATION_DESCRIPTIONS: Record<string, string> = {
  sequence: '顺序关联（A→B）：步骤 1 命中后，在窗口时间内步骤 2 也命中，则触发告警',
  negative: '否定关联（A→¬B）：步骤 1 命中后，在窗口时间内步骤 2 未命中，则触发告警',
}

const RuleForm: React.FC = () => {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [ruleType, setRuleType] = useState<string>('keyword')
  const [correlationType, setCorrelationType] = useState<string>('')
  const [steps, setSteps] = useState<RuleStep[]>([
    { step_order: 0, match_type: 'contains', match_pattern: '', window_seconds: 60, threshold: 1 },
    { step_order: 1, match_type: 'contains', match_pattern: '', window_seconds: 60, threshold: 1 },
  ])
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
      setRuleType(rule.rule_type || 'keyword')
      setCorrelationType(rule.correlation_type || '')
      if (rule.steps && rule.steps.length > 0) {
        setSteps(rule.steps)
      }
    } catch (error) {
      message.error('加载规则失败')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (values: any) => {
    // 序列规则校验
    if (ruleType === 'sequence') {
      if (steps.length < 2) {
        message.error('序列规则至少需要2个步骤')
        return
      }
      for (let i = 0; i < steps.length; i++) {
        if (!steps[i].match_pattern.trim()) {
          message.error(`步骤 ${i + 1} 的匹配模式不能为空`)
          return
        }
      }
    }

    const payload: RuleCreate = {
      ...values,
      rule_type: ruleType,
      correlation_type: ruleType === 'sequence' ? correlationType : null,
      steps: ruleType === 'sequence'
        ? steps.map((s, i) => ({ ...s, step_order: i }))
        : undefined,
    }

    setSubmitting(true)
    try {
      if (isEdit && id) {
        await rulesService.update(Number(id), payload)
        message.success('规则更新成功')
      } else {
        await rulesService.create(payload)
        message.success('规则创建成功')
      }
      navigate('/rules')
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || '操作失败'
      message.error(typeof errorMsg === 'string' ? errorMsg : JSON.stringify(errorMsg))
    } finally {
      setSubmitting(false)
    }
  }

  const addStep = () => {
    setSteps(prev => [
      ...prev,
      { step_order: prev.length, match_type: 'contains', match_pattern: '', window_seconds: 60, threshold: 1 },
    ])
  }

  const removeStep = (index: number) => {
    if (steps.length <= 2) return
    setSteps(prev => prev.filter((_, i) => i !== index))
  }

  const updateStep = (index: number, field: keyof RuleStep, value: any) => {
    setSteps(prev => prev.map((s, i) => i === index ? { ...s, [field]: value } : s))
  }

  return (
    <Card title={isEdit ? '编辑规则' : '创建规则'} loading={loading}>
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        initialValues={{
          enabled: true,
          severity: 'medium',
          match_type: 'contains',
          match_pattern: '-',
          window_seconds: 0,
          threshold: 1,
          group_by: ['namespace', 'pod'],
          cooldown_seconds: 300,
        }}
        style={{ maxWidth: 800 }}
      >
        <Form.Item label="规则名称" name="name"
          rules={[{ required: true, message: '请输入规则名称' }]}>
          <Input placeholder="例如：生产环境错误告警" />
        </Form.Item>

        <Form.Item label="规则类型" name="rule_type">
          <Select
            value={ruleType}
            onChange={(v) => { setRuleType(v); form.setFieldValue('rule_type', v) }}
          >
            <Option value="keyword">关键词匹配</Option>
            <Option value="threshold">窗口阈值</Option>
            <Option value="sequence">序列规则</Option>
          </Select>
        </Form.Item>

        <Form.Item label="严重级别" name="severity"
          rules={[{ required: true, message: '请选择严重级别' }]}>
          <Select>
            <Option value="low">低 (Low)</Option>
            <Option value="medium">中 (Medium)</Option>
            <Option value="high">高 (High)</Option>
            <Option value="critical">严重 (Critical)</Option>
          </Select>
        </Form.Item>

        <Form.Item label="命名空间" name="selector_namespace"
          rules={[{ required: true, message: '请输入命名空间' }]}>
          <Input placeholder="例如：demo" />
        </Form.Item>

        {/* 单条件规则字段 */}
        {ruleType !== 'sequence' && (
          <>
            <Form.Item label="匹配类型" name="match_type"
              rules={[{ required: true, message: '请选择匹配类型' }]}>
              <Select>
                <Option value="contains">关键词包含</Option>
                <Option value="regex">正则表达式</Option>
              </Select>
            </Form.Item>

            <Form.Item label="匹配模式" name="match_pattern"
              rules={[{ required: true, message: '请输入匹配模式' }]}>
              <Input placeholder="例如：ERROR" />
            </Form.Item>

            {ruleType === 'threshold' && (
              <>
                <Form.Item label="时间窗口（秒）" name="window_seconds"
                  tooltip="窗口内命中次数达到阈值时触发告警"
                  rules={[{ required: true }]}>
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>

                <Form.Item label="阈值" name="threshold"
                  tooltip="窗口内命中次数达到此值时触发告警"
                  rules={[{ required: true }]}>
                  <InputNumber min={1} style={{ width: '100%' }} />
                </Form.Item>
              </>
            )}
          </>
        )}

        {/* 序列规则字段 */}
        {ruleType === 'sequence' && (
          <>
            <Form.Item label="关联类型" required>
              <Select
                value={correlationType}
                onChange={setCorrelationType}
                placeholder="请选择关联类型"
              >
                <Option value="sequence">顺序关联（A→B）</Option>
                <Option value="negative">否定关联（A→¬B）</Option>
              </Select>
              {correlationType && (
                <Alert
                  style={{ marginTop: 8 }}
                  type="info"
                  showIcon
                  message={CORRELATION_DESCRIPTIONS[correlationType]}
                />
              )}
            </Form.Item>

            <Divider>条件步骤</Divider>

            {steps.map((step, index) => (
              <Card
                key={index}
                size="small"
                title={`步骤 ${index + 1}`}
                style={{ marginBottom: 12 }}
                extra={
                  steps.length > 2 && (
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => removeStep(index)}
                    >
                      删除
                    </Button>
                  )
                }
              >
                <Space direction="vertical" style={{ width: '100%' }}>
                  <Space wrap>
                    <Form.Item label="匹配类型" style={{ marginBottom: 0 }}>
                      <Select
                        value={step.match_type}
                        onChange={(v) => updateStep(index, 'match_type', v)}
                        style={{ width: 160 }}
                      >
                        <Option value="contains">关键词包含</Option>
                        <Option value="regex">正则表达式</Option>
                      </Select>
                    </Form.Item>
                    <Form.Item label="窗口时间（秒）" style={{ marginBottom: 0 }}>
                      <InputNumber
                        min={1}
                        value={step.window_seconds}
                        onChange={(v) => updateStep(index, 'window_seconds', v ?? 60)}
                        style={{ width: 120 }}
                      />
                    </Form.Item>
                    <Form.Item label="命中次数" style={{ marginBottom: 0 }}>
                      <InputNumber
                        min={1}
                        value={step.threshold}
                        onChange={(v) => updateStep(index, 'threshold', v ?? 1)}
                        style={{ width: 100 }}
                      />
                    </Form.Item>
                  </Space>
                  <Form.Item label="匹配模式" style={{ marginBottom: 0 }}>
                    <Input
                      value={step.match_pattern}
                      onChange={(e) => updateStep(index, 'match_pattern', e.target.value)}
                      placeholder={`步骤 ${index + 1} 的匹配关键词`}
                    />
                  </Form.Item>
                </Space>
              </Card>
            ))}

            <Button
              type="dashed"
              icon={<PlusOutlined />}
              onClick={addStep}
              style={{ marginBottom: 16, width: '100%' }}
            >
              添加步骤
            </Button>
          </>
        )}

        <Form.Item label="分组维度" name="group_by"
          rules={[{ required: true, message: '请选择分组维度' }]}>
          <Select mode="multiple" placeholder="选择分组维度">
            <Option value="namespace">命名空间</Option>
            <Option value="pod">Pod</Option>
            <Option value="container">容器</Option>
          </Select>
        </Form.Item>

        <Form.Item label="冷却时间（秒）" name="cooldown_seconds"
          tooltip="同一告警在冷却期内不会重复发送通知"
          rules={[{ required: true }]}>
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>

        <Form.Item label="启用状态" name="enabled" valuePropName="checked">
          <Switch checkedChildren="启用" unCheckedChildren="停用" />
        </Form.Item>

        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" loading={submitting}>
              {isEdit ? '更新' : '创建'}
            </Button>
            <Button onClick={() => navigate('/rules')}>取消</Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  )
}

export default RuleForm
