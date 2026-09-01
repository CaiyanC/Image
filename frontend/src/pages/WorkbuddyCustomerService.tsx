import CustomerService from './CustomerService'

export default function WorkbuddyCustomerService() {
  return (
    <CustomerService
      pipeline="workbuddy_rag_v1"
      title="智能客服 · WorkBuddy 模式"
      subtitle="自然理解上下文，基于产品资料和知识库回答"
    />
  )
}
