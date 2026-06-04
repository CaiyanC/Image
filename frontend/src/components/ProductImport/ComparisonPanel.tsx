import type { ImportProductData } from '../../utils/excelParser'

interface ComparisonPanelProps {
  existing: ImportProductData
  newData: ImportProductData
  diffFields: string[]
  onConfirm: () => void
  onSkip: () => void
  onClose: () => void
}

function FieldRow({
  label,
  oldVal,
  newVal,
  isDiff,
}: {
  label: string
  oldVal: string
  newVal: string
  isDiff: boolean
}) {
  return (
    <div className={`py-1.5 px-2 rounded text-sm ${isDiff ? 'bg-red-500/10 border border-red-500/20' : ''}`}>
      <div className="text-white/40 text-xs mb-0.5">{label}</div>
      <div className="flex gap-4">
        <span className="flex-1 text-white/60 break-all">{oldVal || '—'}</span>
        <span className={`flex-1 break-all ${isDiff ? 'text-red-300 font-medium' : 'text-white/60'}`}>
          {newVal || '—'}
        </span>
      </div>
    </div>
  )
}

function SectionBlock({
  title,
  fields,
  existing,
  newData,
  diffFields,
}: {
  title: string
  fields: [string, string, (d: ImportProductData) => string][]
  existing: ImportProductData
  newData: ImportProductData
  diffFields: string[]
}) {
  return (
    <div className="mb-4">
      <h4 className="text-sm font-semibold text-blue-400 mb-2">{title}</h4>
      <div className="space-y-1">
        {fields.map(([key, label, getter]) => (
          <FieldRow
            key={key}
            label={label}
            oldVal={getter(existing)}
            newVal={getter(newData)}
            isDiff={diffFields.includes(key)}
          />
        ))}
      </div>
    </div>
  )
}

function jsonDisplay(data: Record<string, unknown>): string {
  try {
    return JSON.stringify(data, null, 1).replace(/[{}"]/g, '').replace(/,/g, '').replace(/^\s+/gm, '')
  } catch {
    return String(data)
  }
}

export default function ComparisonPanel({
  existing,
  newData,
  diffFields,
  onConfirm,
  onSkip,
  onClose,
}: ComparisonPanelProps) {
  const l1Fields: [string, string, (d: ImportProductData) => string][] = [
    ['sku', 'SKU', (d) => d.sku],
    ['barcode', '条形码', (d) => d.barcode],
    ['product_name_cn', '中文名称', (d) => d.product_name_cn],
    ['product_name_en', '英文名称', (d) => d.product_name_en],
    ['brand', '品牌', (d) => d.brand],
    ['series', '系列', (d) => d.series],
    ['category', '系统分类', (d) => d.category],
    ['product_level', '商品分级', (d) => d.product_level],
    ['launch_date', '上市时间', (d) => d.launch_date],
    ['lifecycle_status', '生命周期', (d) => d.lifecycle_status],
    ['person_in_charge', '负责人', (d) => d.person_in_charge],
  ]

  const totalDiffs = diffFields.length

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="bg-slate-900 border border-white/10 rounded-2xl w-full max-w-5xl max-h-[90vh] flex flex-col shadow-2xl">
        <div className="flex items-center justify-between p-5 border-b border-white/10">
          <div>
            <h3 className="text-lg font-bold text-white">
              SKU: {newData.sku} — {newData.product_name_cn}
            </h3>
            <p className="text-sm text-red-400 mt-0.5">
              {totalDiffs > 0 ? `共 ${totalDiffs} 个字段存在差异` : '所有字段一致'}
            </p>
          </div>
          <button onClick={onClose} className="text-white/40 hover:text-white/80 text-xl leading-none">
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <div className="grid grid-cols-2 gap-4 text-xs text-white/30 pb-2 border-b border-white/5 mb-3">
            <span>现有数据（草稿/产品）</span>
            <span>新数据（Excel）</span>
          </div>

          <SectionBlock title="L1 产品身份" fields={l1Fields} existing={existing} newData={newData} diffFields={diffFields} />

          <div className={`mb-4 ${diffFields.includes('specs_data') ? 'bg-red-500/5 border border-red-500/20 rounded-lg p-3' : ''}`}>
            <h4 className="text-sm font-semibold text-purple-400 mb-2">
              L2 物理规格 {diffFields.includes('specs_data') && <span className="text-red-400 text-xs ml-2">有差异</span>}
            </h4>
            <div className="grid grid-cols-2 gap-4">
              <pre className="text-xs text-white/40 whitespace-pre-wrap font-mono">{jsonDisplay(existing.specs_data)}</pre>
              <pre className={`text-xs whitespace-pre-wrap font-mono ${diffFields.includes('specs_data') ? 'text-red-300' : 'text-white/40'}`}>
                {jsonDisplay(newData.specs_data)}
              </pre>
            </div>
          </div>

          <div className={`mb-4 ${diffFields.includes('business_data') ? 'bg-red-500/5 border border-red-500/20 rounded-lg p-3' : ''}`}>
            <h4 className="text-sm font-semibold text-amber-400 mb-2">
              L3 商业价值 {diffFields.includes('business_data') && <span className="text-red-400 text-xs ml-2">有差异</span>}
            </h4>
            <div className="grid grid-cols-2 gap-4">
              <pre className="text-xs text-white/40 whitespace-pre-wrap font-mono">{jsonDisplay(existing.business_data)}</pre>
              <pre className={`text-xs whitespace-pre-wrap font-mono ${diffFields.includes('business_data') ? 'text-red-300' : 'text-white/40'}`}>
                {jsonDisplay(newData.business_data)}
              </pre>
            </div>
          </div>

          <div className={`mb-4 ${diffFields.includes('content_data') ? 'bg-red-500/5 border border-red-500/20 rounded-lg p-3' : ''}`}>
            <h4 className="text-sm font-semibold text-emerald-400 mb-2">
              L4 内容素材 {diffFields.includes('content_data') && <span className="text-red-400 text-xs ml-2">有差异</span>}
            </h4>
            <div className="grid grid-cols-2 gap-4">
              <pre className="text-xs text-white/40 whitespace-pre-wrap font-mono">{jsonDisplay(existing.content_data)}</pre>
              <pre className={`text-xs whitespace-pre-wrap font-mono ${diffFields.includes('content_data') ? 'text-red-300' : 'text-white/40'}`}>
                {jsonDisplay(newData.content_data)}
              </pre>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 p-5 border-t border-white/10 bg-slate-900/80">
          <div className="text-xs text-white/30 mr-auto">差异字段已红色高亮标注</div>
          <button
            onClick={onSkip}
            className="px-5 py-2 rounded-lg border border-white/15 text-white/60 hover:text-white/80 hover:border-white/30 text-sm transition-colors"
          >
            保留原数据不更新
          </button>
          <button
            onClick={onConfirm}
            className="px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
          >
            确认采用新数据
          </button>
        </div>
      </div>
    </div>
  )
}
