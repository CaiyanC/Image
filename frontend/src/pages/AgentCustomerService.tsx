import CustomerService from './CustomerService'

export default function AgentCustomerService() {
  return (
    <CustomerService
      pipeline="workbuddy_agent_v2"
      title="智能客服 · Agent 模式"
      subtitle="由模型理解上下文并自主调用语义 RAG 工具"
    />
  )
}
