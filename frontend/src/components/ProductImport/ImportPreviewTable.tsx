import { useState } from 'react'
import type { ImportRow } from '../../utils/excelParser'
import ComparisonPanel from './ComparisonPanel'

interface ImportPreviewTableProps {
  rows: ImportRow[]
  onConfirm: (selectedRows: ImportRow[]) => Promise<{ created: number; updated: number; skipped: number }>
  onClose: () => void
}

const actionLabels: Record<string, { text: string; className: string }> = {
  create: { text: '新建', className: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' },
  update_consistent: { text: '跳过-一致', className: 'bg-slate-500/20 text-slate-400 border-slate-500/30' },
  update_conflict: { text: '更新', className: 'bg-amber-500/20 text-amber-400 border-amber-500/30' },
}

export default function ImportPreviewTable({ rows, onConfirm, onClose }: ImportPreviewTableProps) {
  const [localRows, setLocalRows] = useState<ImportRow[]>(() =>
    rows.map((r) => ({
      ...r,
      selected: r.action !== 'update_consistent',
    })),
  )
  const [comparingRow, setComparingRow] = useState<ImportRow | null>(null)
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState<{ created: number; updated: number; skipped: number } | null>(null)

  const allSelected = localRows.length > 0 && localRows.every((r) => r.selected)
  const selectedCount = localRows.filter((r) => r.selected).length

  const toggleRow = (index: number) => {
    setLocalRows((prev) =>
      prev.map((r, i) => (i === index ? { ...r, selected: !r.selected } : r)),
    )
  }

  const toggleAll = () => {
    const next = !allSelected
    setLocalRows((prev) => prev.map((r) => ({ ...r, selected: next })))
  }

  const handleConfirm = async () => {
    const selected = localRows.filter((r) => r.selected && r.action !== 'update_consistent')
    if (selected.length === 0) return
    setImporting(true)
    try {
      const res = await onConfirm(selected)
      setResult(res)
    } catch {
    } finally {
      setImporting(false)
    }
  }

  const handleComparisonConfirm = () => {
    if (!comparingRow) return
    setLocalRows((prev) =>
      prev.map((r) =>
        r.index === comparingRow.index ? { ...r, selected: true, confirmed: true } : r,
      ),
    )
    setComparingRow(null)
  }

  const handleComparisonSkip = () => {
    if (!comparingRow) return
    setLocalRows((prev) =>
      prev.map((r) =>
        r.index === comparingRow.index ? { ...r, selected: false, confirmed: true } : r,
      ),
    )
    setComparingRow(null)
  }

  if (result) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
        <div className="bg-slate-900 border border-white/10 rounded-2xl w-full max-w-md p-6 shadow-2xl text-center">
          <div className="text-4xl mb-3">✅</div>
          <h3 className="text-lg font-bold text-white mb-2">导入完成</h3>
          <div className="text-sm text-white/60 space-y-1 mb-4">
            <p>🆕 创建草稿：<span className="text-emerald-400">{result.created}</span> 个</p>
            <p>🔄 更新草稿：<span className="text-amber-400">{result.updated}</span> 个</p>
            <p>⏭️ 跳过一致：<span className="text-slate-400">{result.skipped}</span> 个</p>
          </div>
          <button onClick={onClose} className="px-6 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm transition-colors">
            完成
          </button>
        </div>
      </div>
    )
  }

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
        <div className="bg-slate-900 border border-white/10 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl">
          <div className="flex items-center justify-between p-5 border-b border-white/10">
            <div>
              <h3 className="text-lg font-bold text-white">导入预览</h3>
              <p className="text-sm text-white/40 mt-0.5">
                共 {localRows.length} 条数据，已选 {selectedCount} 条导入草稿箱
              </p>
            </div>
            <button onClick={onClose} className="text-white/40 hover:text-white/80 text-xl leading-none">
              ✕
            </button>
          </div>

          <div className="flex-1 overflow-auto p-5">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-white/40">
                  <th className="text-left py-2 pl-1 w-8">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      className="rounded border-white/20 bg-white/5"
                    />
                  </th>
                  <th className="text-left py-2 px-2">SKU</th>
                  <th className="text-left py-2 px-2">产品名称</th>
                  <th className="text-left py-2 px-2">操作</th>
                  <th className="text-left py-2 px-2">状态</th>
                  <th className="text-right py-2 pr-1 w-20">操作</th>
                </tr>
              </thead>
              <tbody>
                {localRows.map((row, i) => {
                  const action = actionLabels[row.action] || actionLabels.create
                  const isConflict = row.action === 'update_conflict'
                  const isConsistent = row.action === 'update_consistent'
                  return (
                    <tr key={i} className="border-b border-white/5 hover:bg-white/5">
                      <td className="py-2.5 pl-1">
                        <input
                          type="checkbox"
                          checked={row.selected}
                          onChange={() => toggleRow(i)}
                          className="rounded border-white/20 bg-white/5"
                        />
                      </td>
                      <td className="py-2.5 px-2 text-white/80 font-mono text-xs">{row.sku}</td>
                      <td className="py-2.5 px-2 text-white/70">{row.product_name_cn}</td>
                      <td className="py-2.5 px-2">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs border ${action.className}`}>
                          {action.text}
                        </span>
                      </td>
                      <td className="py-2.5 px-2">
                        {isConsistent ? (
                          <span className="text-white/30 text-xs">数据一致，将跳过</span>
                        ) : isConflict ? (
                          <span className="text-red-400 text-xs">
                            {row.diffFields.length > 0
                              ? `有 ${row.diffFields.length} 个字段差异`
                              : '存在差异'}
                          </span>
                        ) : (
                          <span className="text-emerald-400 text-xs">将创建草稿</span>
                        )}
                      </td>
                      <td className="py-2.5 pr-1 text-right">
                        {isConflict && (
                          <button
                            onClick={() => setComparingRow(row)}
                            className="text-xs text-blue-400 hover:text-blue-300 underline"
                          >
                            查看对比
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between p-5 border-t border-white/10 bg-slate-900/80">
            <button onClick={toggleAll} className="text-sm text-white/40 hover:text-white/60">
              {allSelected ? '取消全选' : '全选'}
            </button>
            <div className="flex items-center gap-3">
              <button
                onClick={onClose}
                className="px-4 py-2 rounded-lg border border-white/15 text-white/60 hover:text-white/80 text-sm transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleConfirm}
                disabled={selectedCount === 0 || importing}
                className="px-6 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm font-medium transition-colors"
              >
                {importing ? '导入中...' : `确认导入草稿箱 (${selectedCount})`}
              </button>
            </div>
          </div>
        </div>
      </div>

      {comparingRow && comparingRow.existingData && (
        <ComparisonPanel
          existing={comparingRow.existingData}
          newData={comparingRow.newData}
          diffFields={comparingRow.diffFields}
          onConfirm={handleComparisonConfirm}
          onSkip={handleComparisonSkip}
          onClose={() => setComparingRow(null)}
        />
      )}
    </>
  )
}
