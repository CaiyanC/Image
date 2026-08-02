import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import KnowledgeBase from './KnowledgeBase'

export default function AdminSettings() {
  const navigate = useNavigate()
  const [showKnowledgeBase, setShowKnowledgeBase] = useState(true)

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-4">
      <section className="glass rounded-2xl p-6">
        <h1 className="text-2xl font-bold text-apple-text">系统设置</h1>
        <p className="mt-2 text-sm text-apple-gray-medium">模型、API Key 与授权策略已迁移到专用的模型治理页。为安全起见，已保存的 Key 只能脱敏查看或替换。</p>
        <button onClick={() => navigate('/admin/model-governance')} className="btn-primary mt-4 text-sm">打开模型治理</button>
      </section>

      <section className="overflow-hidden rounded-3xl border border-white/70 bg-white/45 shadow-[0_24px_80px_rgba(15,23,42,0.08)]">
        <button onClick={() => setShowKnowledgeBase((value) => !value)} className="flex w-full items-center justify-between px-5 py-4 text-left">
          <div><h2 className="text-lg font-black text-apple-text">知识库运行</h2><p className="mt-1 text-sm text-apple-gray-medium">仅超级管理员可查看知识库健康度、检索预览和重建任务。</p></div>
          <span className="text-sm font-bold text-teal-700">{showKnowledgeBase ? '收起' : '展开'}</span>
        </button>
        {showKnowledgeBase && <div className="border-t border-black/5"><KnowledgeBase /></div>}
      </section>
    </div>
  )
}
