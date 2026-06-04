import { useState } from 'react'
import FileDropZone from './FileDropZone'
import { parseL5Excel } from '../../utils/excelParser'
import type { L5ImportData } from '../../utils/excelParser'
import { api } from '../../services/api'

interface L5ImporterProps {
  onImportComplete: () => void
}

interface L5FileEntry {
  data: L5ImportData
  status: 'success' | 'error'
  productStatus?: 'exists' | 'missing' | 'unchecked'
  error?: string
}

export default function L5Importer({ onImportComplete }: L5ImporterProps) {
  const [open, setOpen] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [entries, setEntries] = useState<L5FileEntry[]>([])
  const [importing, setImporting] = useState(false)
  const [done, setDone] = useState(false)
  const [summary, setSummary] = useState('')
  const [mode, setMode] = useState<'replace' | 'append'>('replace')

  const handleFiles = async (files: File[]) => {
    setParsing(true)
    setDone(false)
    setSummary('')
    const results: L5FileEntry[] = []

    for (const file of files) {
      try {
        const data = await parseL5Excel(file)
        results.push({ data, status: 'success', productStatus: 'unchecked' })
      } catch (err: unknown) {
        results.push({
          data: { sku: '', fileName: file.name, qaItems: [], reviewItems: [], raw: { qa: [], review: [] } },
          status: 'error',
          error: err instanceof Error ? err.message : '解析失败',
        })
      }
    }

    const validSkus = results.filter((e) => e.status === 'success').map((e) => e.data.sku)
    if (validSkus.length) {
      try {
        const checkResult = await api.products.checkSkus(validSkus)
        for (const entry of results) {
          if (entry.status !== 'success') continue
          entry.productStatus = checkResult.existing[entry.data.sku] ? 'exists' : 'missing'
        }
      } catch {
        for (const entry of results) {
          if (entry.status === 'success') entry.productStatus = 'unchecked'
        }
      }
    }

    setEntries(results)
    setParsing(false)
  }

  const handleImport = async () => {
    setImporting(true)
    setSummary('')

    const importable = entries.filter((e) => e.status === 'success' && e.productStatus === 'exists')
    if (!importable.length) {
      setSummary('没有可导入的文件，请先确认 SKU 已存在于产品库。')
      setImporting(false)
      return
    }

    try {
      const result = await api.products.importQaBatch({
        mode,
        items: importable.map((entry) => ({
          sku: entry.data.sku,
          file_name: entry.data.fileName,
          qa_items: entry.data.qaItems.map((qa) => ({
            no: qa.no,
            question: qa.q,
            answer: qa.a,
            priority: qa.no,
          })),
          review_items: entry.data.reviewItems,
        })),
      })
      setSummary(
        `已处理 ${result.total_files} 个文件，导入 ${result.total_qa_created} 条 Q&A，更新 ${result.total_negative_updated} 个差评话术。`
      )
      setDone(true)
      onImportComplete()
    } catch (err) {
      setSummary(err instanceof Error ? err.message : '导入失败')
    } finally {
      setImporting(false)
    }
  }

  const handleClose = () => {
    setOpen(false)
    setEntries([])
    setDone(false)
    setSummary('')
  }

  const importableCount = entries.filter((e) => e.status === 'success' && e.productStatus === 'exists').length

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="px-4 py-2 bg-green-500 text-white rounded-lg text-sm font-medium hover:bg-green-600 transition-colors flex items-center gap-2"
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 4v16m8-8H4" />
        </svg>
        导入 L5
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="bg-slate-900 border border-white/10 rounded-2xl w-full max-w-2xl shadow-2xl">
            <div className="flex items-center justify-between p-5 border-b border-white/10">
              <h3 className="text-lg font-bold text-white">导入 L5 知识库</h3>
              <button onClick={handleClose} className="text-white/40 hover:text-white/80 text-xl leading-none">
                ×
              </button>
            </div>

            <div className="p-5">
              {done ? (
                <div className="text-center py-4">
                  <p className="text-lg font-bold text-white mb-1">L5 导入完成</p>
                  {summary && <p className="text-sm text-white/60 mt-2">{summary}</p>}
                  <button
                    onClick={handleClose}
                    className="mt-4 px-6 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm transition-colors"
                  >
                    完成
                  </button>
                </div>
              ) : (
                <>
                  <FileDropZone
                    accept=".xlsx,.xls"
                    multiple={true}
                    label="上传 L5 知识库表格（支持多文件）"
                    onFiles={handleFiles}
                  />

                  {parsing && (
                    <p className="text-sm text-blue-400 mt-3 animate-pulse">
                      正在解析并检查 SKU...
                    </p>
                  )}

                  {entries.length > 0 && (
                    <div className="mt-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="text-sm text-white/60 font-medium">解析结果</div>
                        <select
                          value={mode}
                          onChange={(e) => setMode(e.target.value as 'replace' | 'append')}
                          className="bg-white/10 border border-white/10 text-white text-xs rounded-lg px-2 py-1"
                        >
                          <option value="replace">替换已有 QA</option>
                          <option value="append">追加到已有 QA</option>
                        </select>
                      </div>

                      <div className="max-h-80 overflow-y-auto space-y-2 pr-1">
                        {entries.map((entry, i) => (
                          <div
                            key={i}
                            className={`rounded-lg px-3 py-2 text-xs ${
                              entry.status === 'error' || entry.productStatus === 'missing'
                                ? 'bg-red-500/10 border border-red-500/20'
                                : 'bg-white/5 border border-white/5'
                            }`}
                          >
                            {entry.status === 'error' ? (
                              <div>
                                <div className="text-red-400 font-medium truncate">{entry.data.fileName}</div>
                                <div className="text-red-300 mt-0.5">{entry.error}</div>
                              </div>
                            ) : (
                              <div className="flex items-center justify-between gap-3">
                                <div>
                                  <div className="text-white/70 font-medium truncate">{entry.data.fileName}</div>
                                  <div className="text-white/40 mt-0.5">
                                    SKU: {entry.data.sku} · Q&A: {entry.data.qaItems.length} 条 · 差评: {entry.data.reviewItems.length} 条
                                  </div>
                                </div>
                                <span className={`shrink-0 ${entry.productStatus === 'exists' ? 'text-emerald-400' : 'text-red-300'}`}>
                                  {entry.productStatus === 'exists' ? '可导入' : entry.productStatus === 'missing' ? 'SKU 不存在' : '未检查'}
                                </span>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>

                      {summary && <div className="text-sm text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">{summary}</div>}

                      <button
                        onClick={handleImport}
                        disabled={importing || importableCount === 0}
                        className="w-full py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm font-medium transition-colors"
                      >
                        {importing ? '导入中...' : `确认导入知识库 (${importableCount})`}
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
