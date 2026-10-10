import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type LoadingRateCalculation } from '../services/api'

type CalculationMode = 'volume' | 'items'

interface LoadingLine {
  id: string
  sku: string
  cartonCount: string
}

export default function LoadingRateCalculator() {
  const [searchParams] = useSearchParams()
  const initialSku = searchParams.get('sku')?.trim() || ''
  const [mode, setMode] = useState<CalculationMode>(initialSku ? 'items' : 'volume')
  const [actualCargoVolume, setActualCargoVolume] = useState('')
  const [containerUsableVolume, setContainerUsableVolume] = useState('')
  const [items, setItems] = useState<LoadingLine[]>(() => [
    { id: 'line-1', sku: initialSku, cartonCount: '' },
  ])
  const [result, setResult] = useState<LoadingRateCalculation | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const updateItem = (id: string, field: 'sku' | 'cartonCount', value: string) => {
    setItems(current => current.map(item => item.id === id ? { ...item, [field]: value } : item))
  }

  const addItem = () => {
    setItems(current => [...current, { id: `line-${Date.now()}-${current.length}`, sku: '', cartonCount: '' }])
  }

  const removeItem = (id: string) => {
    setItems(current => current.length > 1 ? current.filter(item => item.id !== id) : [{ ...current[0], sku: '', cartonCount: '' }])
  }

  const submit = async (payload: Parameters<typeof api.loadingRates.calculate>[0]) => {
    setLoading(true)
    setError('')
    try {
      const data = await api.loadingRates.calculate(payload)
      setResult(data)
    } catch (err) {
      setResult(null)
      setError(err instanceof Error ? err.message : '计算失败，请稍后重试。')
    } finally {
      setLoading(false)
    }
  }

  const calculate = async () => {
    const usable = Number(containerUsableVolume)
    if (!Number.isFinite(usable) || usable <= 0) {
      setError('请输入大于 0 的集装箱可用体积。')
      return
    }

    if (mode === 'volume') {
      const actual = Number(actualCargoVolume)
      if (!Number.isFinite(actual) || actual < 0) {
        setError('请输入不小于 0 的实际货物体积。')
        return
      }
      await submit({ actual_cargo_volume_m3: actual, container_usable_volume_m3: usable })
      return
    }

    const normalized = items.map(item => ({ sku: item.sku.trim(), cartonCount: Number(item.cartonCount) }))
    if (normalized.some(item => !item.sku)) {
      setError('请填写每一行的 SKU。')
      return
    }
    if (normalized.some(item => !Number.isInteger(item.cartonCount) || item.cartonCount < 1)) {
      setError('装柜箱数必须是大于 0 的整数。')
      return
    }

    // Repeated SKU rows are safe to merge and avoid duplicate lines when the
    // operator splits a shipment while entering it.
    const merged = new Map<string, number>()
    for (const item of normalized) merged.set(item.sku, (merged.get(item.sku) || 0) + item.cartonCount)
    await submit({
      container_usable_volume_m3: usable,
      items: Array.from(merged, ([sku, carton_count]) => ({ sku, carton_count })),
    })
  }

  return (
    <main className="mx-auto max-w-4xl px-4 pb-12 pt-8 md:px-6">
      <div className="mb-8">
        <Link to="/products" className="text-sm font-bold text-teal-700 hover:text-teal-600">← 返回产品资料</Link>
        <p className="mt-6 text-sm font-bold text-teal-700">装柜 / 出货计算</p>
        <h1 className="mt-2 text-3xl font-black text-apple-text">装载率计算</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-apple-gray-medium">
          装载率 = 实际货物占用体积 ÷ 集装箱可用体积 × 100%。可以直接输入汇总体积，也可以按产品数据库里的外箱尺寸和本次装柜箱数自动汇总。
        </p>
      </div>

      <section className="glass rounded-3xl p-6 md:p-8">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="装载率计算方式">
          <button type="button" role="tab" aria-selected={mode === 'volume'} onClick={() => { setMode('volume'); setError(''); setResult(null) }} className={`rounded-full px-4 py-2 text-sm font-bold ${mode === 'volume' ? 'bg-teal-700 text-white' : 'bg-white/70 text-apple-gray-dark'}`}>
            直接输入总体积
          </button>
          <button type="button" role="tab" aria-selected={mode === 'items'} onClick={() => { setMode('items'); setError(''); setResult(null) }} className={`rounded-full px-4 py-2 text-sm font-bold ${mode === 'items' ? 'bg-teal-700 text-white' : 'bg-white/70 text-apple-gray-dark'}`}>
            按 SKU 和箱数计算
          </button>
        </div>

        {mode === 'volume' ? (
          <div className="mt-5">
            <VolumeInput
              label="实际货物占用体积（m³）"
              hint="可按外箱体积 × 本次装柜箱数汇总"
              value={actualCargoVolume}
              onChange={setActualCargoVolume}
              placeholder="例如 25.6"
            />
          </div>
        ) : (
          <div className="mt-5 rounded-2xl border border-teal-100 bg-teal-50/55 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-black text-teal-950">装柜明细</div>
                <p className="mt-1 text-xs leading-5 text-teal-900/70">系统会读取产品数据库中的外箱长、宽、高；缺少完整尺寸的 SKU 会提示补齐。</p>
              </div>
              <button type="button" onClick={addItem} className="rounded-full bg-white px-3 py-1.5 text-xs font-bold text-teal-700">+ 添加 SKU</button>
            </div>
            <div className="mt-3 space-y-2">
              {items.map((item, index) => (
                <div key={item.id} className="grid gap-2 sm:grid-cols-[1fr_180px_auto]">
                  <label className="sr-only" htmlFor={`loading-sku-${item.id}`}>第 {index + 1} 行 SKU</label>
                  <input id={`loading-sku-${item.id}`} value={item.sku} onChange={event => updateItem(item.id, 'sku', event.target.value)} placeholder="SKU，例如 CW-C95" className="rounded-xl border border-black/10 bg-white px-3 py-2 text-sm outline-none focus:border-teal-500" />
                  <label className="sr-only" htmlFor={`loading-count-${item.id}`}>第 {index + 1} 行装柜箱数</label>
                  <input id={`loading-count-${item.id}`} type="number" min="1" step="1" value={item.cartonCount} onChange={event => updateItem(item.id, 'cartonCount', event.target.value)} placeholder="装柜箱数" className="rounded-xl border border-black/10 bg-white px-3 py-2 text-sm outline-none focus:border-teal-500" />
                  <button type="button" onClick={() => removeItem(item.id)} className="rounded-xl bg-white px-3 py-2 text-xs font-bold text-red-600 hover:bg-red-50">移除</button>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="mt-5">
          <VolumeInput
            label="集装箱可用体积（m³）"
            hint="使用实际内部可用尺寸，必要时扣除托盘等占用空间"
            value={containerUsableVolume}
            onChange={setContainerUsableVolume}
            placeholder="例如 67.5"
          />
        </div>
        <button
          type="button"
          onClick={() => void calculate()}
          disabled={loading}
          className="mt-6 rounded-2xl bg-teal-700 px-5 py-3 text-sm font-bold text-white transition hover:bg-teal-600 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? '计算中…' : '计算装载率'}
        </button>
      </section>

      {error && <div className="mt-5 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>}

      {result && (
        <section className="mt-5 glass rounded-3xl p-6 md:p-8">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-sm font-bold text-apple-gray-medium">本次装柜装载率</p>
              <p className={`mt-2 text-5xl font-black ${result.over_capacity ? 'text-red-600' : 'text-teal-700'}`}>
                {result.loading_rate_pct.toFixed(2)}%
              </p>
            </div>
            <span className={`rounded-full px-3 py-1 text-xs font-bold ${result.over_capacity ? 'bg-red-100 text-red-700' : 'bg-teal-100 text-teal-700'}`}>
              {result.over_capacity ? '超过可用容量' : '容量范围内'}
            </span>
          </div>
          <div className="mt-6 grid gap-3 text-sm md:grid-cols-2">
            <Summary label="实际货物体积" value={`${result.actual_cargo_volume_m3.toFixed(6)} m³`} />
            <Summary label="集装箱可用体积" value={`${result.container_usable_volume_m3.toFixed(6)} m³`} />
          </div>
          {result.items.length > 0 && (
            <div className="mt-5 rounded-2xl bg-white/60 p-4">
              <div className="text-sm font-black text-apple-text">本次装柜明细</div>
              <div className="mt-2 space-y-2 text-xs text-apple-gray-dark">
                {result.items.map(item => <div key={item.sku} className="flex flex-wrap justify-between gap-2"><span>{item.sku} · {item.carton_count} 箱</span><span>{item.cargo_volume_m3.toFixed(6)} m³</span></div>)}
              </div>
            </div>
          )}
          <p className="mt-5 text-xs leading-5 text-apple-gray-medium">{result.formula}。结果保留四位小数，超过 100% 只提示异常，不会被系统强行截断。</p>
        </section>
      )}
    </main>
  )
}

function VolumeInput({ label, hint, value, onChange, placeholder }: { label: string; hint: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  return (
    <label className="block">
      <span className="block text-sm font-bold text-apple-text">{label}</span>
      <span className="mt-1 block text-xs leading-5 text-apple-gray-medium">{hint}</span>
      <input
        type="number"
        min="0"
        step="0.000001"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="mt-3 w-full rounded-2xl border border-gray-200 bg-white/70 px-4 py-3 text-sm outline-none focus:border-teal-500"
      />
    </label>
  )
}

function Summary({ label, value }: { label: string; value: string }) {
  return <div className="rounded-2xl bg-white/60 px-4 py-3"><span className="text-apple-gray-medium">{label}</span><strong className="ml-2 text-apple-text">{value}</strong></div>
}
