import { useEffect, useRef, useState } from 'react'
import { api, type EcommercePrecheck, type ToolRun } from '../services/api'

const modes = [
  { value: 'ecommerce', title: '电商数据分析表' }, { value: 'kepule', title: '周月报' }, { value: 'amazon', title: '亚马逊库存' },
] as const
type Mode = (typeof modes)[number]['value']

export default function EcommerceDataFill() {
  const [mode, setMode] = useState<Mode>('ecommerce')
  const [step, setStep] = useState(1)
  const [draft, setDraft] = useState<ToolRun | null>(null)
  const [precheck, setPrecheck] = useState<EcommercePrecheck | null>(null)
  const [runs, setRuns] = useState<ToolRun[]>([])
  const [parameters, setParameters] = useState({ cycle_type: '周', cycle_code: '', start_date: '', end_date: '' })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const input = useRef<HTMLInputElement>(null)

  const refreshRuns = () => api.tools.ecommerceDataFill.listRuns().then(setRuns).catch((err: Error) => setError(err.message))
  useEffect(() => { refreshRuns() }, [])
  useEffect(() => { if (runs.some((run) => run.status === 'queued' || run.status === 'running')) { const timer = window.setInterval(refreshRuns, 3000); return () => clearInterval(timer) } }, [runs])

  function reset(nextMode: Mode) { setMode(nextMode); setDraft(null); setPrecheck(null); setStep(1); setError('') }
  async function addFiles(files: File[]) {
    if (!files.length) return
    setLoading(true); setError('')
    try {
      const next = draft ? await api.tools.ecommerceDataFill.addDraftFiles(draft.id, files) : await api.tools.ecommerceDataFill.createDraft(mode, files)
      setDraft(next)
      setPrecheck(await api.tools.ecommerceDataFill.precheckDraft(next.id))
    } catch (err) { setError(err instanceof Error ? err.message : '上传或识别文件失败') } finally { setLoading(false); if (input.current) input.current.value = '' }
  }
  async function check() { if (!draft) { setError('请先上传 Excel 文件。'); return }; setLoading(true); try { setPrecheck(await api.tools.ecommerceDataFill.precheckDraft(draft.id)); setStep(3) } catch (err) { setError(err instanceof Error ? err.message : '预检查失败') } finally { setLoading(false) } }
  async function confirmRun() {
    if (!draft || !precheck?.can_run) return
    if (!window.confirm('请确认已关闭本次使用的 Excel 文件。确认后将开始填写。')) return
    setLoading(true); setError('')
    try { await api.tools.ecommerceDataFill.confirmDraft(draft.id, parameters); setStep(4); await refreshRuns() } catch (err) { setError(err instanceof Error ? err.message : '开始填写失败') } finally { setLoading(false) }
  }

  return <main className="mx-auto max-w-6xl px-4 pb-12 pt-8 md:px-6">
    <p className="text-sm font-bold text-teal-700">财务部工具</p><h1 className="mt-2 text-3xl font-black text-apple-text">电商数据分析表自动填写</h1>
    <div className="mt-6 grid grid-cols-4 gap-2 text-center text-xs font-bold">{['导入文件', '确认条件', '预检查', '查看结果'].map((label, index) => <div key={label} className={`rounded-full px-3 py-2 ${step >= index + 1 ? 'bg-teal-700 text-white' : 'bg-white/55 text-apple-gray-medium'}`}>{index + 1}. {label}</div>)}</div>
    {error && <p className="mt-4 rounded-2xl bg-red-50 px-4 py-3 text-sm text-red-600">{error}</p>}
    <section className="glass mt-6 rounded-3xl p-6">
      {step === 1 && <><h2 className="text-lg font-black text-apple-text">1. 导入并识别文件</h2><p className="mt-2 text-sm text-apple-gray-medium">可多次补充上传；系统会按原工具规则自动识别文件用途。</p><div className="mt-4 grid gap-3 md:grid-cols-3">{modes.map((item) => <button key={item.value} onClick={() => reset(item.value)} className={`rounded-2xl border p-3 font-bold ${mode === item.value ? 'border-teal-500 bg-teal-50 text-teal-700' : 'border-black/5 bg-white/45 text-apple-gray-dark'}`}>{item.title}</button>)}</div><label className="mt-5 flex cursor-pointer items-center justify-between rounded-2xl border border-dashed border-teal-300 bg-white/50 px-4 py-5 text-sm"><span>{loading ? '正在上传和识别…' : draft ? `已导入 ${draft.input_files.length} 个文件，可继续补充` : '选择第一批 Excel 文件'}</span><input ref={input} className="hidden" type="file" accept=".xlsx" multiple onChange={(event) => addFiles(Array.from(event.target.files || []))} /></label>{precheck && <Slots precheck={precheck} />}<button disabled={!draft || loading} onClick={() => setStep(2)} className="mt-5 rounded-full bg-teal-700 px-5 py-2.5 text-sm font-bold text-white disabled:opacity-50">下一步：确认条件</button></>}
      {step === 2 && <><h2 className="text-lg font-black text-apple-text">2. 确认周期和日期</h2><p className="mt-2 text-sm text-apple-gray-medium">这些值会按原工具逻辑写入本次结果。</p><div className="mt-5 grid gap-3 md:grid-cols-2">{([['cycle_code','周次编码，例如 W27'], ['start_date','开始日期，YYYY-MM-DD'], ['end_date','结束日期，YYYY-MM-DD']] as const).map(([key, label]) => <input key={key} value={parameters[key]} placeholder={label} onChange={(event) => setParameters({ ...parameters, [key]: event.target.value })} className="rounded-xl border border-black/10 bg-white/60 px-4 py-3 text-sm" />)}<select value={parameters.cycle_type} onChange={(event) => setParameters({ ...parameters, cycle_type: event.target.value })} className="rounded-xl border border-black/10 bg-white/60 px-4 py-3 text-sm"><option>周</option><option>月</option></select></div><button onClick={check} disabled={loading} className="mt-5 rounded-full bg-teal-700 px-5 py-2.5 text-sm font-bold text-white">运行预检查</button></>}
      {step === 3 && <><h2 className="text-lg font-black text-apple-text">3. 预检查</h2>{precheck && <><Slots precheck={precheck} /><p className={`mt-4 text-sm font-bold ${precheck.can_run ? 'text-teal-700' : 'text-red-600'}`}>{precheck.can_run ? '检查通过，可以开始填写。' : '请先返回上一步补齐必需文件。'}</p></>}<button onClick={confirmRun} disabled={!precheck?.can_run || loading} className="mt-5 rounded-full bg-teal-700 px-5 py-2.5 text-sm font-bold text-white disabled:opacity-50">确认并开始填写</button></>}
      {step === 4 && <><h2 className="text-lg font-black text-apple-text">4. 查看结果</h2><div className="mt-4 space-y-3">{runs.map((run) => <div key={run.id} className="rounded-2xl bg-white/55 px-4 py-3"><strong>{run.status === 'succeeded' ? '已完成' : run.status === 'failed' ? '失败' : '处理中'}</strong><span className="ml-2 text-xs text-apple-gray-medium">{new Date(run.created_at).toLocaleString()}</span>{run.error_message && <p className="mt-1 text-sm text-red-600">{run.error_message}</p>}{run.output_files.map((file, index) => <button key={file.relative_path} onClick={() => api.tools.ecommerceDataFill.download(run.id, index, file.display_name).catch((err: Error) => setError(err.message))} className="ml-3 rounded-full bg-teal-50 px-3 py-1 text-xs font-bold text-teal-700">下载 {file.display_name}</button>)}</div>)}</div><button onClick={() => reset(mode)} className="mt-5 rounded-full bg-teal-700 px-5 py-2.5 text-sm font-bold text-white">新建一次填写</button></>}
    </section>
  </main>
}

function Slots({ precheck }: { precheck: EcommercePrecheck }) { return <div className="mt-5 grid gap-2 sm:grid-cols-2">{precheck.slots.map((slot) => <div key={slot.role} className={`rounded-xl px-3 py-2 text-sm ${slot.recognized ? 'bg-teal-50 text-teal-800' : slot.required ? 'bg-red-50 text-red-700' : 'bg-amber-50 text-amber-800'}`}><strong>{slot.recognized ? '已识别' : slot.required ? '必需缺失' : '建议补充'}</strong> · {slot.label}</div>)}</div> }
