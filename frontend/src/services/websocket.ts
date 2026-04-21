/**
 * WebSocket 客户端：订阅 /ws/alerts 实时告警推送
 * - 自动 5s 重连
 * - onMessage 回调外部处理新告警 payload
 * - onReconnect 回调触发时建议主动调 alertsService.list() 补齐断线期间漏推
 */

export type AlertWsPayload = {
  id: number
  rule_id: number
  fingerprint: string
  severity: string
  status: string
  hit_count: number
  last_seen: string | null
  group_by: Record<string, string>
}

export type WsOptions = {
  onMessage: (payload: AlertWsPayload) => void
  onOpen?: () => void
  onReconnect?: () => void
  onClose?: () => void
  onError?: (err: Event) => void
}

const RECONNECT_INTERVAL_MS = 5000

export class AlertsWebSocket {
  private ws: WebSocket | null = null
  private reconnectTimer: number | null = null
  private closed = false
  private hasConnectedOnce = false
  private url: string
  private options: WsOptions

  constructor(url: string, options: WsOptions) {
    this.url = url
    this.options = options
  }

  connect(): void {
    if (this.closed) return
    try {
      this.ws = new WebSocket(this.url)
    } catch (e) {
      this.scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      if (this.hasConnectedOnce && this.options.onReconnect) {
        this.options.onReconnect()
      }
      if (this.options.onOpen) {
        this.options.onOpen()
      }
      this.hasConnectedOnce = true
    }

    this.ws.onmessage = (event) => {
      try {
        const payload: AlertWsPayload = JSON.parse(event.data)
        this.options.onMessage(payload)
      } catch (e) {
        // ignore malformed payload
      }
    }

    this.ws.onerror = (event) => {
      if (this.options.onError) this.options.onError(event)
    }

    this.ws.onclose = () => {
      this.ws = null
      if (this.options.onClose) this.options.onClose()
      if (!this.closed) this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, RECONNECT_INTERVAL_MS)
  }

  close(): void {
    this.closed = true
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      try {
        this.ws.close()
      } catch {
        // ignore
      }
      this.ws = null
    }
  }
}

/** 基于页面当前协议/host 构造 ws URL */
export function buildAlertsWsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/alerts`
}
