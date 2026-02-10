import api from './api'

export interface Alert {
  id: number
  rule_id: number
  fingerprint: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  status: string
  first_seen: string
  last_seen: string
  hit_count: number
  group_by: Record<string, string>
  sample_log: {
    timestamp: string
    content: string
    namespace: string
    pod: string
    container?: string
  }
  last_notified_at?: string | null
  created_at: string
  updated_at: string
}

export interface AlertListResponse {
  total: number
  page: number
  page_size: number
  items: Alert[]
}

export const alertsService = {
  // 获取告警列表
  async list(params?: {
    page?: number
    page_size?: number
    severity?: string
    rule_id?: number
  }): Promise<AlertListResponse> {
    return api.get('/alerts', { params })
  },

  // 获取告警详情
  async get(id: number): Promise<Alert> {
    return api.get(`/alerts/${id}`)
  },
}
