import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type KnowledgeFileRecord } from '../services/api'

// Reuse the knowledge-file permissions and controlled download endpoint.
// Unpublished SKUs can carry documents without inventing a product/asset row.
export default function SourceDocumentLibrary() {
  const [records, setRecords] = useState<KnowledgeFileRecord[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    api.knowledgeBase.files(100).then(result => { if (active) setRecords(result.items) })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : '资料列表读取失败') })
    return () => { active = false }
  }, [])
  return <section aria-label="说明与客服资料" className="rounded-xl border border-slate-200 bg-white p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="font-semibold">说明与客服资料</h2>
      <Link to="/file-knowledge" className="text-sm text-teal-700">管理全部文件</Link>
    </div>
    <p className="mt-2 text-sm text-slate-500">与文件知识库共用原始资料。草稿或待审资料可查阅，不代表已用于智能客服；新SKU无需借用老款资料。</p>
    {error && <p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}
    <div className="mt-3 max-h-64 space-y-2 overflow-y-auto">
      {records.map(record => <div key={record.document_id} className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm">
        <span className="min-w-0 flex-1 break-all font-medium">{record.file_name}</span>
        <span>{record.related_skus.join(' / ') || '未绑定SKU'}</span>
        {!!record.source_qa_count && <span>{record.source_qa_count}条FAQ</span>}
        <span className={record.is_active === false ? 'text-amber-700' : 'text-slate-500'}>{record.is_active === false ? '仅归档 / 待核对' : record.parse_status === 'done' ? '解析完成' : record.parse_status}</span>
        <a href={api.files.knowledgeDownloadUrl(record.document_id)} className="text-teal-700" download>下载原文</a>
      </div>)}
    </div>
  </section>
}
