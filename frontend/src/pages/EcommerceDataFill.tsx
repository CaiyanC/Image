import { useEffect, useRef, useState } from 'react'
import { api, type ToolRun } from '../services/api'

const modes = [
  { value: 'ecommerce', title: '电商数据分析表', detail: '填写电商数据分析相关表格' },
  { value: 'kepule', title: '周月报', detail: '填写周报、月报模板' },
  { value: 'amazon', title: '亚马逊库存', detail: '填写亚马逊库存相关表格' },
] as const

function statusText(status: ToolRun['status']) {
  return ({ queued: '排队中', running: '处理中', succeeded: '已完成', failed: '失败' } as const)[status]
}

export default function EcommerceDataFill() {
  const [mode, setMode] = useState<(typeof modes)[number]['value']>('ecommerce')
  const [files, setFiles] = useState<File[]>([])
  const [runs, setRuns] = useState<ToolRun[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const refresh = () => api.tools.ecommerceDataFill.listRuns().then(setRuns).catch((err: Error) => setError(err.message))
  useEffect(() => { refresh() }, [])
  useEffect(() => {
    if (!runs.some((run) => run.status === 'queued' || run.status === 'running')) return
    const timer = window.setInterval(refresh, 3000)
    return () => window.clearInterval(timer)
  }, [runs])

  async function submit() {
    if (!files.length) { setError('请先选择需要处理的 Excel 文件。'); return }
    setLoading(true); setError('')
    try {
      await api.tools.ecommerceDataFill.submit({ mode, files })
      setFiles([])
      if (fileInput.current) fileInput.current.value = ''
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交任务失败')
    } finally { setLoading(false) }
  }

  return (
    <main className="mx-auto max-w-6xl px-4 pb-12 pt-8 md:px-6">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-3">
        <div><p className="text-sm font-bold text-teal-700">财务部工具</p><h1 className="mt-2 text-3xl font-black text-apple-text">电商数据分析表自动填写</h1></div>
        <button onClick={refresh} className="rounded-full px-4 py-2 text-sm font-bold text-teal-700 hover:bg-teal-50">刷新记录</button>
      </div>
      <section className="glass rounded-3xl p-6">
        <h2 className="text-lg font-black text-apple-text">新建处理任务</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {modes.map((item) => <button key={item.value} onClick={() => setMode(item.value)} className={`rounded-2xl border p-4 text-left ${mode === item.value ? 'border-teal-500 bg-teal-50' : 'border-black/5 bg-white/45'}`}><strong className="block text-apple-text">{item.title}</strong><span className="mt-1 block text-xs text-apple-gray-medium">{item.detail}</span></button>)}
        </div>
        <label className="mt-5 flex cursor-pointer items-center justify-between rounded-2xl border border-dashed border-teal-300 bg-white/50 px-4 py-5 text-sm text-apple-gray-dark">
          <span>{files.length ? `已选择 ${files.length} 个文件：${files.map((file) => file.name).join('、')}` : '点击选择 Excel 文件（支持 .xlsx）'}</span>
          <input ref={fileInput} className="hidden" type="file" accept=".xlsx" multiple onChange={(event) => setFiles(Array.from(event.target.files || []))} />
        </label>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        <button disabled={loading} onClick={submit} className="mt-5 rounded-full bg-teal-700 px-5 py-2.5 text-sm font-bold text-white disabled:opacity-50">{loading ? '正在提交…' : '开始处理'}</button>
      </section>
      <section className="mt-7"><h2 className="text-lg font-black text-apple-text">我的处理记录</h2><div className="mt-3 space-y-3">
        {runs.map((run) => <div key={run.id} className="glass flex flex-wrap items-center justify-between gap-3 rounded-2xl px-5 py-4"><div><p className="font-bold text-apple-text">{statusText(run.status)} · {String(run.parameters.mode || '')}</p><p className="mt-1 text-xs text-apple-gray-medium">{new Date(run.created_at).toLocaleString()}</p>{run.error_message && <p className="mt-1 text-xs text-red-600">{run.error_message}</p>}</div><div className="flex flex-wrap gap-2">{run.output_files.map((file, index) => <button key={file.relative_path} onClick={() => api.tools.ecommerceDataFill.download(run.id, index, file.display_name).catch((err: Error) => setError(err.message))} className="rounded-full bg-teal-50 px-3 py-1.5 text-xs font-bold text-teal-700">下载 {file.display_name}</button>)}</div></div>)}
        {!runs.length && <p className="rounded-2xl bg-white/45 px-5 py-6 text-sm text-apple-gray-medium">还没有处理记录。</p>}
      </div></section>
    </main>
  )
}
