import { useState } from 'react'
import FileDropZone from './FileDropZone'
import ImportPreviewTable from './ImportPreviewTable'
import { parseL1L4Excel, compareFields } from '../../utils/excelParser'
import type { ImportProductData, ImportRow } from '../../utils/excelParser'
import { api } from '../../services/api'

interface L1L4ImporterProps {
  onImportComplete: () => void
}

export default function L1L4Importer({ onImportComplete }: L1L4ImporterProps) {
  const [open, setOpen] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewRows, setPreviewRows] = useState<ImportRow[] | null>(null)

  const handleFiles = async (files: File[]) => {
    const file = files[0]
    if (!file) return
    setError(null)
    setParsing(true)

    try {
      const parsed = await parseL1L4Excel(file)
      if (parsed.length === 0) {
        setError('未找到有效数据行，请确认表格第6行起包含SKU和产品数据')
        setParsing(false)
        return
      }

      const skus = parsed.map((p) => p.sku)
      const checkResult = await api.products.checkSkus(skus)

      const rows: ImportRow[] = parsed.map((item, index) => {
        const existing = checkResult.existing[item.sku]
        let action: ImportRow['action'] = 'create'
        let diffFields: string[] = []
        let existingData: ImportProductData | undefined

        if (existing) {
          const ex = existing as Record<string, unknown>
          const draftData = (ex.draft_data || {}) as Record<string, unknown>
          const isDraft = ex.source === 'draft'
          existingData = {
            sku: (ex.sku as string) || item.sku,
            product_name_cn: (isDraft ? String(draftData.product_name_cn || '') : (ex.product_name_cn as string)) || '',
            product_name_en: (isDraft ? String(draftData.product_name_en || '') : (ex.product_name_en as string)) || '',
            barcode: (isDraft ? String(draftData.barcode || '') : (ex.barcode as string)) || '',
            brand: (isDraft ? String(draftData.brand || '') : (ex.brand as string)) || '',
            series: (isDraft ? String(draftData.series || '') : (ex.series as string)) || '',
            category: (isDraft ? String(draftData.category || '') : (ex.category as string)) || '',
            product_level: (isDraft ? String(draftData.product_level || '') : (ex.product_level as string)) || '',
            launch_date: (isDraft ? String(draftData.launch_date || '') : (ex.launch_date as string)) || '',
            lifecycle_status: (isDraft ? String(draftData.lifecycle_status || '') : (ex.lifecycle_status as string)) || '',
            person_in_charge: (isDraft ? String(draftData.person_in_charge || '') : (ex.person_in_charge as string)) || '',
            specs_data: (isDraft ? (draftData.specs as Record<string, unknown>) : {}) || {},
            business_data: (isDraft ? (draftData.business as Record<string, unknown>) : {}) || {},
            content_data: (isDraft ? (draftData.content as Record<string, unknown>) : {}) || {},
          }

          diffFields = compareFields(existingData!, item)

          if (diffFields.length === 0) {
            action = 'update_consistent'
          } else {
            action = 'update_conflict'
          }
        }

        return {
          index,
          sku: item.sku,
          product_name_cn: item.product_name_cn,
          action,
          existingData,
          newData: item,
          diffFields,
          selected: action !== 'update_consistent',
          confirmed: action === 'create' || action === 'update_consistent',
        }
      })

      setPreviewRows(rows)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '文件解析失败')
    } finally {
      setParsing(false)
    }
  }

  const handleConfirm = async (selectedRows: ImportRow[]) => {
    const items = selectedRows.map((r) => {
      const sd = { ...(r.newData.specs_data as Record<string, unknown>) }
      const bd = { ...(r.newData.business_data as Record<string, unknown>) }
      const cd = { ...(r.newData.content_data as Record<string, unknown>) }

      return {
        sku: r.newData.sku,
        product_name_cn: r.newData.product_name_cn,
        product_name_en: r.newData.product_name_en,
        barcode: r.newData.barcode,
        brand: r.newData.brand,
        series: r.newData.series,
        category: r.newData.category,
        product_level: r.newData.product_level,
        launch_date: r.newData.launch_date,
        lifecycle_status: r.newData.lifecycle_status,
        person_in_charge: r.newData.person_in_charge,
        specs_data: sd,
        business_data: bd,
        content_data: cd,
      }
    })

    const result = await api.drafts.createBatch(items)
    return result
  }

  const handleImportDone = () => {
    setPreviewRows(null)
    setOpen(false)
    onImportComplete()
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="px-4 py-2 bg-green-500 text-white rounded-lg text-sm font-medium hover:bg-green-600 transition-colors flex items-center gap-2"
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
        </svg>
        导入 L1-L4
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="bg-slate-900 border border-white/10 rounded-2xl w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between p-5 border-b border-white/10">
              <h3 className="text-lg font-bold text-white">导入 L1-L4 产品数据</h3>
              <button onClick={() => setOpen(false)} className="text-white/40 hover:text-white/80 text-xl leading-none">
                ✕
              </button>
            </div>

            <div className="p-5">
              <FileDropZone
                accept=".xlsx,.xls"
                multiple={false}
                label="上传 L1-L4 产品表格"
                onFiles={handleFiles}
              />
              {parsing && (
                <p className="text-sm text-blue-400 mt-3 animate-pulse">正在解析表格...</p>
              )}
              {error && (
                <p className="text-sm text-red-400 mt-3">{error}</p>
              )}
            </div>
          </div>
        </div>
      )}

      {previewRows && (
        <ImportPreviewTable
          rows={previewRows}
          onConfirm={handleConfirm}
          onClose={handleImportDone}
        />
      )}
    </>
  )
}
