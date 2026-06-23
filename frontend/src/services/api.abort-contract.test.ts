import { api } from './api'

const controller = new AbortController()

api.customerService.askStream(
  { question: 'cancel stream test', conversation_id: null },
  () => undefined,
  controller.signal,
)
