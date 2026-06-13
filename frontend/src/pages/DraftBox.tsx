import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../services/api'
import type { ProductDraft } from '../types'

export default function DraftBox() {
  const navigate = useNavigate()
  const [drafts, setDrafts] = useState<ProductDraft[]>([])
  const [loading, setLoading] = useState(true)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [batchMode, setBatchMode] = useState(false)
  const [batchConfirm, setBatchConfirm] = useState<'delete' | 'publish' | null>(null)
  const [notice, setNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  useEffect(() => {
    loadDrafts()
  }, [])

  async function loadDrafts() {
    setLoading(true)
    try {
      const result = await api.drafts.list(0, 1000)
      setDrafts(result.items)
    } catch (err) {
      console.error('Failed to load drafts:', err)
    } finally {
      setLoading(false)
    }
  }

  async function handlePublish(id: string) {
    try {
      await api.drafts.publish(id)
      setDrafts(drafts.filter(d => d.id !== id))
      showNotice('success', '草稿已发布')
    } catch (err: any) {
      console.error('Publish failed:', err)
      showNotice('error', err?.message || '发布失败，请打开草稿检查必填字段')
    }
  }

  async function handleDelete(id: string) {
    try {
      await api.drafts.delete(id)
      setDrafts(drafts.filter(d => d.id !== id))
      setDeleteConfirmId(null)
    } catch (err) {
      console.error('Delete failed:', err)
    }
  }

  function toggleSelect(id: string) {
    const next = new Set(selectedIds)
    if (next.has(id)) { next.delete(id) } else { next.add(id) }
    setSelectedIds(next)
  }

  function toggleSelectAll() {
    if (selectedIds.size === filteredDrafts.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(filteredDrafts.map(d => d.id)))
    }
  }

  async function handleBatchDelete() {
    let count = 0
    for (const id of selectedIds) {
      try { await api.drafts.delete(id); count++ } catch {}
    }
    setDrafts(drafts.filter(d => !selectedIds.has(d.id)))
    setSelectedIds(new Set())
    setBatchMode(false)
    setBatchConfirm(null)
    showNotice('success', `已删除 ${count} 个草稿`)
  }

  async function handleBatchPublish() {
    let count = 0
    const successIds = new Set<string>()
    const failures: string[] = []
    for (const id of selectedIds) {
      try {
        await api.drafts.publish(id)
        count++
        successIds.add(id)
      } catch (err: any) {
        const draft = drafts.find(d => d.id === id)
        failures.push(`${draft?.sku || id}: ${err?.message || '发布失败'}`)
      }
    }
    setDrafts(drafts.filter(d => !successIds.has(d.id)))
    setSelectedIds(new Set())
    setBatchMode(false)
    setBatchConfirm(null)
    if (failures.length > 0) {
      showNotice('error', `成功发布 ${count} 个，失败 ${failures.length} 个：${failures.join('；')}`)
    } else {
      showNotice('success', `已发布 ${count} 个草稿`)
    }
  }

  function showNotice(type: 'success' | 'error', text: string) {
    setNotice({ type, text })
    window.setTimeout(() => setNotice(null), 3500)
  }

  const filteredDrafts = drafts.filter(d => {
    const data = d.draft_data || {}
    return (d.sku?.toLowerCase() || '').includes(searchQuery.toLowerCase()) ||
      (String(data.product_name_cn || '').toLowerCase()).includes(searchQuery.toLowerCase()) ||
      (String(data.product_name_en || '').toLowerCase()).includes(searchQuery.toLowerCase())
  })

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    )
  }

  return (
    <div className="p-4 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <button onClick={() => navigate('/products')} className="text-sm text-blue-500 hover:text-blue-700 mb-1 flex items-center gap-1">
            ← 返回产品管理
          </button>
          <h1 className="text-2xl font-bold text-apple-text tracking-tight">📋 草稿箱</h1>
          <p className="text-sm text-apple-gray-medium mt-1">保存的产品草稿，可继续编辑或发布</p>
        </div>
        <div className="flex items-center gap-2">
          {batchMode ? (
            <>
              <span className="text-sm text-apple-gray-medium">{selectedIds.size} 个已选</span>
              <button onClick={() => { setBatchMode(false); setSelectedIds(new Set()) }}
                className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors">取消</button>
              <button onClick={() => selectedIds.size > 0 && setBatchConfirm('publish')}
                className="px-3 py-1.5 text-sm bg-green-500 text-white rounded-lg hover:bg-green-600 transition-colors disabled:opacity-50"
                disabled={selectedIds.size === 0}>批量发布</button>
              <button onClick={() => selectedIds.size > 0 && setBatchConfirm('delete')}
                className="px-3 py-1.5 text-sm bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors disabled:opacity-50"
                disabled={selectedIds.size === 0}>批量删除</button>
            </>
          ) : (
            <>
              <button onClick={() => setBatchMode(true)}
                className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-200 transition-colors">
                批量操作
              </button>
              <button onClick={() => navigate('/products/create')}
                className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-600 transition-colors">
                + 新建草稿
              </button>
            </>
          )}
        </div>
      </div>

      {notice && (
        <div className={`mb-4 rounded-xl border px-4 py-3 text-sm ${
          notice.type === 'success'
            ? 'border-green-200 bg-green-50 text-green-700'
            : 'border-red-200 bg-red-50 text-red-700'
        }`}>
          {notice.text}
        </div>
      )}

      {batchConfirm && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
          <p className="text-sm text-red-600">
            {batchConfirm === 'delete' ? `确认删除选中的 ${selectedIds.size} 个草稿吗？此操作不可撤销。` : `确认发布选中的 ${selectedIds.size} 个草稿吗？`}
          </p>
          <div className="flex justify-end gap-2 mt-3">
            <button onClick={() => setBatchConfirm(null)} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">取消</button>
            <button onClick={() => batchConfirm === 'delete' ? handleBatchDelete() : handleBatchPublish()}
              className={`px-3 py-1.5 text-sm text-white rounded-lg ${batchConfirm === 'delete' ? 'bg-red-500 hover:bg-red-600' : 'bg-green-500 hover:bg-green-600'}`}>
              确认{batchConfirm === 'delete' ? '删除' : '发布'}
            </button>
          </div>
        </div>
      )}

      <div className="flex items-center gap-3 mb-4">
        <input
          type="text"
          placeholder="搜索草稿 SKU 或名称..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="flex-1 px-4 py-2 bg-white/50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-blue-400"
        />
        {batchMode && filteredDrafts.length > 0 && (
          <label className="flex items-center gap-1.5 text-sm text-apple-gray-medium cursor-pointer whitespace-nowrap">
            <input type="checkbox" checked={selectedIds.size === filteredDrafts.length && filteredDrafts.length > 0}
              onChange={toggleSelectAll} className="w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-400" />
            全选
          </label>
        )}
      </div>

      {filteredDrafts.length === 0 ? (
        <div className="glass p-12 text-center">
          <p className="text-apple-gray-medium">暂无草稿数据</p>
          <p className="text-sm text-apple-gray-medium/60 mt-1">点击右上角"+ 新建草稿"开始录入</p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredDrafts.map((draft) => (
            <div key={draft.id} className={`glass rounded-xl p-4 transition-colors ${selectedIds.has(draft.id) ? 'ring-2 ring-blue-400 bg-blue-50/50' : ''}`}>
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3 flex-1">
                  {batchMode && (
                    <input type="checkbox" checked={selectedIds.has(draft.id)} onChange={() => toggleSelect(draft.id)}
                      className="mt-1 w-4 h-4 rounded border-gray-300 text-blue-500 focus:ring-blue-400" />
                  )}
                  <div className="flex-1">
                  <div className="font-semibold text-apple-text">{draft.sku || '未设置 SKU'}</div>
                  <p className="text-sm text-apple-gray-medium mt-1">{String((draft.draft_data as any)?.product_name_cn || (draft.draft_data as any)?.product_name_en || '未命名')}</p>
                  <div className="flex items-center gap-4 mt-2 text-xs text-apple-gray-medium">
                    <span>创建于 {new Date(draft.created_at || '').toLocaleDateString()}</span>
                    {draft.updated_at && draft.updated_at !== draft.created_at && (
                      <span>更新于 {new Date(draft.updated_at).toLocaleDateString()}</span>
                    )}
                  </div>
                </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => navigate(`/products/create/${draft.id}`)}
                    className="px-3 py-1.5 text-sm text-blue-600 hover:bg-blue-50 rounded-lg transition-colors">
                    编辑
                  </button>
                  <button onClick={() => handlePublish(draft.id)}
                    className="px-3 py-1.5 text-sm text-green-600 hover:bg-green-50 rounded-lg transition-colors">
                    发布
                  </button>
                  <button onClick={() => setDeleteConfirmId(draft.id)}
                    className="px-3 py-1.5 text-sm text-red-500 hover:bg-red-50 rounded-lg transition-colors">
                    删除
                  </button>
                </div>
              </div>

              {deleteConfirmId === draft.id && (
                <div className="mt-4 bg-red-50 border border-red-200 rounded-lg p-3">
                  <p className="text-sm text-red-600">确认删除草稿 {draft.sku || '此草稿'} 吗？此操作不可撤销。</p>
                  <div className="flex justify-end gap-2 mt-2">
                    <button onClick={() => setDeleteConfirmId(null)} className="px-3 py-1 text-sm text-gray-600 hover:bg-gray-100 rounded-lg">
                      取消
                    </button>
                    <button onClick={() => handleDelete(draft.id)} className="px-3 py-1 text-sm text-red-600 hover:bg-red-100 rounded-lg">
                      确认删除
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
