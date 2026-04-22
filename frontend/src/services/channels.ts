import api from './api'

export interface WecomTestRequest {
  webhook_url: string
  mentioned_mobile_list?: string[]
}

export interface WecomTestResponse {
  success: boolean
  errcode: number
  errmsg: string
}

export const channelsService = {
  async testWecom(req: WecomTestRequest): Promise<WecomTestResponse> {
    return api.post('/channels/test', req)
  },
}
