import api from './api'

export interface Rule {
  id: number
  name: string
  enabled: boolean
  severity: 'low' | 'medium' | 'high' | 'critical'
  selector_namespace: string
  selector_labels?: Record<string, string> | null
  match_type: 'contains' | 'regex'
  match_pattern: string
  window_seconds: number
  threshold: number
  group_by: string[]
  cooldown_seconds: number
  last_query_time?: string | null
  created_at: string
  updated_at: string
}

export interface RuleCreate {
  name: string
  enabled?: boolean
  severity: 'low' | 'medium' | 'high' | 'critical'
  selector_namespace: string
  selector_labels?: Record<string, string> | null
  match_type: 'contains' | 'regex'
  match_pattern: string
  window_seconds?: number
  threshold?: number
  group_by: string[]
  cooldown_seconds?: number
}

export const rulesService = {
  // 获取规则列表
  async list(params?: { enabled?: boolean }): Promise<Rule[]> {
    return api.get('/rules', { params })
  },

  // 获取规则详情
  async get(id: number): Promise<Rule> {
    return api.get(`/rules/${id}`)
  },

  // 创建规则
  async create(data: RuleCreate): Promise<Rule> {
    return api.post('/rules', data)
  },

  // 更新规则
  async update(id: number, data: Partial<RuleCreate>): Promise<Rule> {
    return api.put(`/rules/${id}`, data)
  },

  // 删除规则
  async delete(id: number): Promise<void> {
    return api.delete(`/rules/${id}`)
  },

  // 启用规则
  async enable(id: number): Promise<Rule> {
    return api.patch(`/rules/${id}/enable`)
  },

  // 停用规则
  async disable(id: number): Promise<Rule> {
    return api.patch(`/rules/${id}/disable`)
  },
}
