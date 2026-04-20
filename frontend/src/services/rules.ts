import api from './api'

export interface RuleStep {
  step_order: number
  match_type: 'contains' | 'regex'
  match_pattern: string
  window_seconds: number
  threshold: number
}

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
  rule_type: 'keyword' | 'threshold' | 'sequence'
  correlation_type?: 'sequence' | 'negative' | null
  steps: RuleStep[]
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
  rule_type?: 'keyword' | 'threshold' | 'sequence'
  correlation_type?: 'sequence' | 'negative' | null
  steps?: RuleStep[]
}

export const rulesService = {
  async list(params?: { enabled?: boolean }): Promise<Rule[]> {
    return api.get('/rules', { params })
  },

  async get(id: number): Promise<Rule> {
    return api.get(`/rules/${id}`)
  },

  async create(data: RuleCreate): Promise<Rule> {
    return api.post('/rules', data)
  },

  async update(id: number, data: Partial<RuleCreate>): Promise<Rule> {
    return api.put(`/rules/${id}`, data)
  },

  async delete(id: number): Promise<void> {
    return api.delete(`/rules/${id}`)
  },

  async enable(id: number): Promise<Rule> {
    return api.patch(`/rules/${id}/enable`)
  },

  async disable(id: number): Promise<Rule> {
    return api.patch(`/rules/${id}/disable`)
  },
}

