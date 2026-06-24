import { useEffect, useState } from 'react'
import { api } from '../services/api'
import KnowledgeBase from './KnowledgeBase'

interface ModelItem {
  id: string
  name: string
  type: string
  description: string
  api_key: string
  api_base_url: string
  api_format: string
  api_model: string
  txt2img_url: string
  img2img_url: string
  chat_url: string
  embedding_url: string
  enabled: boolean
  actual?: boolean
  managed_by?: string
}

const typeLabels: Record<string, string> = {
  image: '图像',
  video: '视频',
  chat: '客服聊天',
  embedding: '向量',
}

const emptyModel: ModelItem = {
  id: '',
  name: '',
  type: 'chat',
  description: '',
  api_key: '',
  api_base_url: '',
  api_format: 'openai',
  api_model: '',
  txt2img_url: '',
  img2img_url: '',
  chat_url: '',
  embedding_url: '',
  enabled: true,
}

const deepseekPreset: ModelItem = {
  ...emptyModel,
  id: 'deepseek-customer-service',
  name: 'DeepSeek 客服模型',
  type: 'chat',
  description: '智能客服推荐配置',
  api_base_url: 'https://api.deepseek.com',
  api_format: 'openai',
  api_model: 'deepseek-v4-flash',
  chat_url: 'https://api.deepseek.com/chat/completions',
}

export default function AdminSettings() {
  const [models, setModels] = useState<ModelItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showKnowledgeBase, setShowKnowledgeBase] = useState(true)

  useEffect(() => {
    loadModels()
  }, [])

  async function loadModels() {
    try {
      const data = await api.admin.getModels()
      setModels(data.map(normalizeModel))
    } catch {
      setMessage('加载配置失败')
    } finally {
      setLoading(false)
    }
  }

  function normalizeModel(model: Partial<ModelItem>): ModelItem {
    return { ...emptyModel, ...model, api_model: model.api_model || model.id || '' }
  }

  async function save(nextModels = models) {
    setSaving(true)
    setMessage('')
    try {
      await api.admin.updateModels(nextModels)
      setModels(nextModels)
      setMessage('保存成功')
      setTimeout(() => setMessage(''), 2500)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  function update(id: string, field: keyof ModelItem, value: string | boolean) {
    setModels((prev) => prev.map((model) => model.id === id ? { ...model, [field]: value } : model))
  }

  async function addDeepSeek() {
    const exists = models.some((model) => model.id === deepseekPreset.id)
    const next = exists
      ? models.map((model) => model.id === deepseekPreset.id ? { ...model, ...deepseekPreset, api_key: model.api_key } : model)
      : [deepseekPreset, ...models]
    setExpandedId(deepseekPreset.id)
    await save(next)
  }

  async function addBlank() {
    const id = `model-${Date.now()}`
    const model = { ...emptyModel, id, name: '新模型', api_model: id }
    setExpandedId(id)
    await save([model, ...models])
  }

  async function remove(id: string) {
    await save(models.filter((model) => model.id !== id))
  }

  if (loading) {
    return <div className="p-4 max-w-5xl mx-auto text-apple-gray-medium">加载中...</div>
  }

  return (
    <div className="p-4 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-apple-text tracking-tight">模型与 API 配置</h1>
          <p className="text-sm text-apple-gray-medium mt-1">图片生成、智能客服、向量知识库统一在这里配置和查看。</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={addDeepSeek} disabled={saving} className="px-4 py-2 text-sm bg-emerald-500 text-white rounded-lg hover:bg-emerald-600 disabled:opacity-50">
            添加 DeepSeek 客服
          </button>
          <button onClick={addBlank} disabled={saving} className="px-4 py-2 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50">
            添加模型
          </button>
          <button onClick={() => save()} disabled={saving} className="btn-primary px-5 py-2 text-sm disabled:opacity-50">
            {saving ? '保存中...' : '保存全部'}
          </button>
        </div>
      </div>

      {message && (
        <div className={`px-4 py-3 rounded-xl text-sm mb-4 ${message.includes('成功') ? 'bg-green-50 text-green-600' : 'bg-red-50 text-red-600'}`}>
          {message}
        </div>
      )}

      <div className="space-y-4">
        {models.map((model) => {
          const expanded = expandedId === model.id
          return (
            <section key={model.id} className="glass rounded-2xl overflow-hidden">
              <button
                onClick={() => setExpandedId(expanded ? null : model.id)}
                className="w-full flex items-center justify-between px-5 py-4 text-left border-b border-black/5"
              >
                <div className="flex items-center gap-3">
                  <span className={`w-2.5 h-2.5 rounded-full ${model.enabled ? 'bg-green-500' : 'bg-gray-300'}`} />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm px-2 py-0.5 rounded-full bg-blue-50 text-blue-600">{typeLabels[model.type] || model.type}</span>
                      <span className="text-xs text-apple-gray-medium">{model.api_format}</span>
                      {model.actual && (
                        <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-100">实际使用</span>
                      )}
                    </div>
                    <h2 className="text-lg font-semibold text-apple-text mt-1">{model.name || model.id}</h2>
                  </div>
                </div>
                <span className="text-apple-gray-medium">{expanded ? '收起' : '展开'}</span>
              </button>

              {expanded && (
                <div className="p-5 space-y-5">
                  {model.actual && model.managed_by && (
                    <div className="rounded-xl border border-emerald-100 bg-emerald-50/80 px-4 py-3 text-sm text-emerald-800">
                      这是后端当前实际使用的配置，密钥来自 <span className="font-mono">{model.managed_by}</span>。
                    </div>
                  )}

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <Field label="配置 ID" hint="系统内部配置标识" value={model.id} onChange={(v) => update(model.id, 'id', v)} />
                    <Field label="显示名称" hint="页面展示名称" value={model.name} onChange={(v) => update(model.id, 'name', v)} />
                    <Field label="API 模型名" hint="请求体里的 model，例如 deepseek-v4-flash" value={model.api_model} onChange={(v) => update(model.id, 'api_model', v)} />
                    <SelectField label="类型" value={model.type} onChange={(v) => update(model.id, 'type', v)} options={[
                      ['image', '图像 Image'],
                      ['video', '视频 Video'],
                      ['chat', '客服聊天 Chat'],
                      ['embedding', '向量 Embedding'],
                    ]} />
                    <SelectField label="API 格式" value={model.api_format} onChange={(v) => update(model.id, 'api_format', v)} options={[
                      ['openai', 'OpenAI 兼容'],
                      ['gemini', 'Gemini'],
                    ]} />
                    <Field label="API Base URL" hint="例如 https://api.deepseek.com" value={model.api_base_url} onChange={(v) => update(model.id, 'api_base_url', v)} />
                  </div>

                  {model.type === 'image' && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <Field label="文生图接口 URL" value={model.txt2img_url} onChange={(v) => update(model.id, 'txt2img_url', v)} />
                      <Field label="图生图接口 URL" value={model.img2img_url} onChange={(v) => update(model.id, 'img2img_url', v)} />
                    </div>
                  )}

                  {model.type === 'chat' && (
                    <Field label="聊天接口 URL" hint="DeepSeek 填 https://api.deepseek.com/chat/completions" value={model.chat_url} onChange={(v) => update(model.id, 'chat_url', v)} />
                  )}

                  {model.type === 'embedding' && (
                    <Field label="Embedding 接口 URL" value={model.embedding_url} onChange={(v) => update(model.id, 'embedding_url', v)} />
                  )}

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <Field label="API Key" value={model.api_key} type="password" onChange={(v) => update(model.id, 'api_key', v)} />
                    <Field label="描述" value={model.description} onChange={(v) => update(model.id, 'description', v)} />
                  </div>

                  <div className="flex items-center justify-between pt-3 border-t border-black/5">
                    <label className="flex items-center gap-3 text-sm text-apple-text">
                      <input type="checkbox" checked={model.enabled} onChange={(e) => update(model.id, 'enabled', e.target.checked)} />
                      启用
                    </label>
                    <div className="flex items-center gap-3">
                      <button onClick={() => remove(model.id)} className="px-3 py-2 text-sm text-red-500 hover:bg-red-50 rounded-lg">删除</button>
                      <button onClick={() => save()} disabled={saving} className="btn-primary px-5 py-2 text-sm disabled:opacity-50">保存</button>
                    </div>
                  </div>
                </div>
              )}
            </section>
          )
        })}
      </div>

      <div className="mt-8 overflow-hidden rounded-3xl border border-white/70 bg-white/45 shadow-[0_24px_80px_rgba(15,23,42,0.08)]">
        <button
          onClick={() => setShowKnowledgeBase((value) => !value)}
          className="flex w-full items-center justify-between px-5 py-4 text-left"
        >
          <div>
            <h2 className="text-lg font-black text-apple-text">知识库运维</h2>
            <p className="mt-1 text-sm text-apple-gray-medium">仅超级管理员可见。这里直接查看知识库健康、检索预览和重建任务。</p>
          </div>
          <span className="text-sm font-bold text-teal-700">{showKnowledgeBase ? '收起' : '展开'}</span>
        </button>
        {showKnowledgeBase && (
          <div className="border-t border-black/5">
            <KnowledgeBase />
          </div>
        )}
      </div>
    </div>
  )
}

function Field({ label, hint, value, type = 'text', onChange }: { label: string; hint?: string; value: string; type?: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-apple-text mb-1">{label}</span>
      <input type={type} value={value || ''} onChange={(e) => onChange(e.target.value)} className="glass-input w-full px-3 py-2 text-sm" />
      {hint && <span className="block text-xs text-apple-gray-medium mt-1">{hint}</span>}
    </label>
  )
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: string[][]; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="block text-sm font-medium text-apple-text mb-1">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="glass-input w-full px-3 py-2 text-sm">
        {options.map(([optionValue, text]) => <option key={optionValue} value={optionValue}>{text}</option>)}
      </select>
    </label>
  )
}
