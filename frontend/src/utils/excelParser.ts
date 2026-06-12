import * as XLSX from 'xlsx'

export interface ImportProductData {
  sku: string
  product_name_cn: string
  product_name_en: string
  barcode: string
  brand: string
  series: string
  category: string
  product_level: string
  launch_date: string
  lifecycle_status: string
  person_in_charge: string
  specs_data: Record<string, unknown>
  business_data: Record<string, unknown>
  content_data: Record<string, unknown>
}

export interface ImportRow {
  index: number
  sku: string
  product_name_cn: string
  action: 'create' | 'update_consistent' | 'update_conflict'
  existingData?: ImportProductData
  newData: ImportProductData
  diffFields: string[]
  selected: boolean
  confirmed: boolean
}

export interface L5ImportData {
  sku: string
  fileName: string
  qaItems: { no?: number; q: string; a: string }[]
  reviewItems: { no?: number; keyword: string; response: string }[]
  raw: {
    qa: Record<string, unknown>[]
    review: Record<string, unknown>[]
  }
}

export interface DimensionLine {
  label: string
  value: string
  unit: string
}

export interface CapacityLine {
  label: string
  value: string
}

// ── Utility parsers ──────────────────────────────────────────────

export function parseDate(raw: unknown): string {
  if (raw === null || raw === undefined || raw === '') return ''
  if (typeof raw === 'number' && raw > 40000 && raw < 80000) {
    const date = new Date((raw - 25569) * 86400 * 1000)
    const y = date.getUTCFullYear()
    const m = String(date.getUTCMonth() + 1).padStart(2, '0')
    const d = String(date.getUTCDate()).padStart(2, '0')
    return `${y}-${m}-${d}`
  }
  const s = String(raw).trim()
  if (/^\d+(\.\d+)?$/.test(s)) {
    const serial = Number(s)
    if (serial > 40000 && serial < 80000) {
      const date = new Date((serial - 25569) * 86400 * 1000)
      const y = date.getUTCFullYear()
      const m = String(date.getUTCMonth() + 1).padStart(2, '0')
      const d = String(date.getUTCDate()).padStart(2, '0')
      return `${y}-${m}-${d}`
    }
  }
  const m = s.match(/(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})/)
  if (m) {
    return `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`
  }
  return s
}

export function parseMultilineToArray(raw: string): string[] {
  if (!raw) return []
  return String(raw)
    .split(/\n+/)
    .map((line) => line.replace(/^\d+[\.\、\)]\s*/, '').trim())
    .filter(Boolean)
}

export function parseCommaSeparated(raw: string): string[] {
  if (!raw) return []
  return String(raw)
    .split(/[\n,，、]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

export function parseDimensionLines(raw: string): DimensionLine[] {
  if (!raw) return []
  const lines = String(raw).split(/\n+/).filter(Boolean)
  const result: DimensionLine[] = []
  for (const line of lines) {
    const trimmed = line.trim()
    const labelMatch = trimmed.match(/^([^:：]+)[：:]\s*(.+)/)
    if (labelMatch) {
      const label = labelMatch[1].trim()
      const rest = labelMatch[2].trim()
      const unitMatch = rest.match(/^(.+?)\s+(cm|mm|英寸|inch)$/i)
      if (unitMatch) {
        result.push({ label, value: unitMatch[1].trim(), unit: unitMatch[2] })
      } else {
        result.push({ label, value: rest, unit: '' })
      }
    } else {
      const unitMatch = trimmed.match(/^(.+?)\s+(cm|mm|英寸|inch)$/i)
      if (unitMatch) {
        result.push({ label: '', value: unitMatch[1].trim(), unit: unitMatch[2] })
      } else {
        result.push({ label: '', value: trimmed, unit: '' })
      }
    }
  }
  return result
}

export function parseCapacityLines(raw: string): CapacityLine[] {
  if (!raw) return []
  const lines = String(raw).split(/\n+/).filter(Boolean)
  const result: CapacityLine[] = []
  for (const line of lines) {
    const trimmed = line.trim()
    const m = trimmed.match(/^(\D+)(\d[\d.]*\s*[a-zA-Z]+.*)$/)
    if (m) {
      result.push({ label: m[1].replace(/[：:]\s*$/, '').trim(), value: m[2].trim() })
    } else {
      result.push({ label: '', value: trimmed })
    }
  }
  return result
}

export function parseCompetitors(raw: string): { name: string }[] {
  if (!raw) return []
  return String(raw)
    .split(/\n+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((name) => ({ name }))
}

export function parseSearchKeywords(raw: string): { keyword: string; priority: string }[] {
  if (!raw) return []
  const result: { keyword: string; priority: string }[] = []
  String(raw)
    .split(/\n+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .forEach((line) => {
      const match = line.match(/^([ABC])级[：:]\s*(.+)$/)
      if (match) {
        const priority = match[1]
        const keywords = match[2].split(/[,，]+/).map((s) => s.trim()).filter(Boolean)
        keywords.forEach((kw) => {
          result.push({ keyword: kw, priority })
        })
      }
    })
  return result
}

// ── Helper ───────────────────────────────────────────────────────

function getCell(row: unknown[], colMap: Record<string, number>, key: string): string {
  const idx = colMap[key]
  if (idx === undefined || idx < 0 || idx >= row.length) return ''
  const v = row[idx]
  if (v === null || v === undefined) return ''
  if (typeof v === 'number') {
    if (Number.isInteger(v) && v >= 1e10) {
      return String(v)
    }
    return String(v)
  }
  return String(v).trim()
}

// ── Column header name → field mapping ──────────────────────────
// 产品库元数据.xlsx real format: headers at row 4, data from row 6

const HEADER_MAP: Record<string, string> = {
  'SKU': 'sku',
  '条形码': 'barcode',
  '商品中文名称': 'product_name_cn',
  '商品英文名称': 'product_name_en',
  '上架渠道': 'listing_channel',
  '售卖地区': 'sales_region',
  '品牌': 'brand',
  '系列': 'series',
  '系统分类': 'category',
  '商品分级': 'product_level',
  '上市时间': 'launch_date',
  '生命周期': 'lifecycle_status',
  '负责人': 'person_in_charge',
  '尺寸信息': 'size_info',
  '容量信息': 'capacity',
  '毛重(g)': 'gross_weight_g',
  '主体材质': 'body_material',
  '主色系': 'color',
  '表面处理': 'surface_finish',
  '适用热源': 'heat_source',
  '功率（炉具类）': 'power',
  '技术优势': 'technical_advantages',
  '认证信息': 'certifications',
  '使用说明': 'usage_instruction',
  '核心卖点 TOP5': 'top_selling_points',
  '目标人群': 'target_audience',
  '差异化定位': 'positioning',
  '价格定位带': 'price_positioning',
  '情感价值': 'emotional_value',
  '使用场景': 'usage_scenarios',
  '竞品对标': 'competitor_benchmark',
  '标题（英文）': 'title_en',
  '标题（中文）': 'title_cn',
  '产品长描述（英文）': 'long_description_en',
  '产品长描述（中文）': 'long_description_cn',
  '搜索关键词库': 'search_keywords',
}

const NORMALIZED_HEADER_MAP = Object.fromEntries(
  Object.entries(HEADER_MAP).map(([header, field]) => [normalizeHeader(header), field]),
)

function normalizeHeader(value: unknown): string {
  return String(value || '').replace(/\s+/g, '').replace(/^#+/, '').trim()
}

function resolveHeaderField(header: unknown): string {
  const raw = String(header || '').trim()
  return HEADER_MAP[raw] || NORMALIZED_HEADER_MAP[normalizeHeader(raw)] || ''
}

function buildColumnMap(headerRow: unknown[]): Record<string, number> {
  const colMap: Record<string, number> = {}
  for (let i = 0; i < headerRow.length; i++) {
    const raw = String(headerRow[i] || '').trim()
    const field = resolveHeaderField(raw)
    if (!field) continue

    colMap[raw] = i
    colMap[normalizeHeader(raw)] = i
    colMap[field] = i
    for (const [canonicalHeader, canonicalField] of Object.entries(HEADER_MAP)) {
      if (canonicalField === field) {
        colMap[canonicalHeader] = i
        colMap[normalizeHeader(canonicalHeader)] = i
      }
    }
  }
  return colMap
}

function findL1L4HeaderRow(rows: unknown[][]): number {
  const maxRows = Math.min(rows.length, 20)
  for (let i = 0; i < maxRows; i++) {
    const colMap = buildColumnMap(rows[i] || [])
    const hasSku = colMap['SKU'] !== undefined || colMap['sku'] !== undefined
    const hasName = colMap['商品中文名称'] !== undefined || colMap['product_name_cn'] !== undefined
    if (hasSku && hasName) return i
  }
  return -1
}

// ── Main parser: 产品库元数据.xlsx ───────────────────────────────

export function parseL1L4Excel(file: File): Promise<ImportProductData[]> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const data = new Uint8Array(e.target!.result as ArrayBuffer)
        const wb = XLSX.read(data, { type: 'array' })
        const sheetName = wb.SheetNames[0]
        const sheet = wb.Sheets[sheetName]
        const rows = XLSX.utils.sheet_to_json<unknown[]>(sheet, { header: 1 })

        if (rows.length < 2) {
          resolve([])
          return
        }

        const headerRowIndex = findL1L4HeaderRow(rows)
        const headerRow = rows[headerRowIndex] as string[]
        const colMap = buildColumnMap(headerRow || [])

        // Must have at least SKU column
        if (headerRowIndex < 0 || colMap['SKU'] === undefined) {
          reject(new Error('未找到 SKU 列，请确认表格格式为产品库元数据标准模板'))
          return
        }

        const results: ImportProductData[] = []

        for (let i = headerRowIndex + 1; i < rows.length; i++) {
          const row = rows[i] as unknown[]
          if (!row || row.length === 0) continue
          if (String(row[0] || '').trim() === '示例') continue

          const sku = getCell(row, colMap, 'SKU')
          if (!sku) continue

          // L1: Product identity
          const productNameCn = getCell(row, colMap, '商品中文名称')
          const productNameEn = getCell(row, colMap, '商品英文名称')
          const barcode = getCell(row, colMap, '条形码')
          const brand = getCell(row, colMap, '品牌')
          const series = getCell(row, colMap, '系列')
          const category = getCell(row, colMap, '系统分类')
          const productLevel = getCell(row, colMap, '商品分级')
          const launchDateRaw = getCell(row, colMap, '上市时间')
          const launchDate = parseDate(launchDateRaw || row[colMap['上市时间'] ?? -1])
          const lifecycleStatus = getCell(row, colMap, '生命周期')
          const personInCharge = getCell(row, colMap, '负责人')

          // Channels & regions (M2M source text, kept in data for draft storage)
          const listingChannelRaw = getCell(row, colMap, '上架渠道')
          const salesRegionRaw = getCell(row, colMap, '售卖地区')
          const listingChannel = parseCommaSeparated(listingChannelRaw)
          const salesRegion = parseCommaSeparated(salesRegionRaw)

          // L2: Specs
          const sizeInfoRaw = getCell(row, colMap, '尺寸信息')
          const capacityRaw = getCell(row, colMap, '容量信息')
          const grossWeightRaw = getCell(row, colMap, '毛重(g)')
          const grossWeightG = grossWeightRaw ? parseFloat(grossWeightRaw) || 0 : 0
          const bodyMaterial = getCell(row, colMap, '主体材质')
          const color = getCell(row, colMap, '主色系')
          const surfaceFinish = getCell(row, colMap, '表面处理')
          const heatSourceRaw = getCell(row, colMap, '适用热源')
          const heatSource = heatSourceRaw
            ? String(heatSourceRaw).split(/[\n,，、、\s]+/).map(s => s.trim()).filter(Boolean).join(', ')
            : ''
          const power = getCell(row, colMap, '功率（炉具类）')
          const technicalAdvantages = parseMultilineToArray(getCell(row, colMap, '技术优势'))
          const certifications = parseMultilineToArray(getCell(row, colMap, '认证信息'))
          const usageInstruction = getCell(row, colMap, '使用说明')

          // Parse structured dimension/capacity for UI editing
          const dimParsed = parseDimensionLines(sizeInfoRaw)
          const capParsed = parseCapacityLines(capacityRaw)

          // L3: Business
          const topSellingPoints = parseMultilineToArray(getCell(row, colMap, '核心卖点 TOP5'))
          const targetAudienceRaw = getCell(row, colMap, '目标人群')
          const targetAudience = targetAudienceRaw
            ? String(targetAudienceRaw).split(/[\n,，、、\s]+/).map(s => s.trim()).filter(Boolean).join(', ')
            : ''
          const positioning = getCell(row, colMap, '差异化定位')
          const pricePositioning = getCell(row, colMap, '价格定位带')
          const emotionalValue = getCell(row, colMap, '情感价值')
          const usageScenarios = parseMultilineToArray(getCell(row, colMap, '使用场景'))
          const competitorBenchmark = parseCompetitors(getCell(row, colMap, '竞品对标'))

          // L4: Content
          const titleEn = getCell(row, colMap, '标题（英文）')
          const titleCn = getCell(row, colMap, '标题（中文）')
          const longDescriptionEn = getCell(row, colMap, '产品长描述（英文）')
          const longDescriptionCn = getCell(row, colMap, '产品长描述（中文）')
          const searchKeywordsRaw = getCell(row, colMap, '搜索关键词库')

          results.push({
            sku,
            product_name_cn: productNameCn || sku,
            product_name_en: productNameEn,
            barcode,
            brand,
            series,
            category,
            product_level: productLevel,
            launch_date: launchDate,
            lifecycle_status: lifecycleStatus,
            person_in_charge: personInCharge,
            specs_data: {
              size_info: dimParsed.length > 0 ? dimParsed : sizeInfoRaw,
              capacity: capParsed.length > 0 ? capParsed : capacityRaw,
              gross_weight_g: grossWeightG,
              body_material: bodyMaterial,
              color,
              surface_finish: surfaceFinish,
              heat_source: heatSource,
              power,
              technical_advantages: technicalAdvantages,
              certifications,
              usage_instruction: usageInstruction,
              sales_region: salesRegion,
            },
            business_data: {
              top_selling_points: topSellingPoints,
              target_audience: targetAudience,
              positioning,
              price_positioning: pricePositioning,
              emotional_value: emotionalValue,
              usage_scenarios: usageScenarios,
              competitor_benchmark: competitorBenchmark,
              listing_channel: listingChannel,
            },
            content_data: {
              title_en: titleEn,
              title_cn: titleCn,
              long_description_en: longDescriptionEn,
              long_description_cn: longDescriptionCn,
              listing_en: longDescriptionEn,
              listing_cn: longDescriptionCn,
              search_keywords: parseSearchKeywords(searchKeywordsRaw),
              search_keywords_raw: searchKeywordsRaw,
            },
          })
        }

        resolve(results)
      } catch (err) {
        reject(err)
      }
    }
    reader.onerror = () => reject(new Error('文件读取失败'))
    reader.readAsArrayBuffer(file)
  })
}

// ── L5 parser: separate QA Excel files (L5 to be built later) ───

export function parseL5Excel(file: File): Promise<L5ImportData> {
  return new Promise((resolve, reject) => {
    const name = file.name.replace(/\.xlsx?$/i, '')
    const sku = name.split('_')[0]?.trim() || name

    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const data = new Uint8Array(e.target!.result as ArrayBuffer)
        const wb = XLSX.read(data, { type: 'array' })

        const qaItems: { no?: number; q: string; a: string }[] = []
        const reviewItems: { no?: number; keyword: string; response: string }[] = []

        const names = wb.SheetNames

        function findSheet(pattern: RegExp): string | undefined {
          return names.find((n) => pattern.test(n))
        }

        const qaSheetName = findSheet(/Q&A|问答/i)
        const reviewSheetName = findSheet(/差评|高频词|话术/i)

        function flushQA(cur: { no?: number; q?: string; a?: string }) {
          if (cur.q?.trim() && cur.a?.trim()) {
            qaItems.push({ no: cur.no, q: cur.q.trim(), a: cur.a.trim() })
          }
        }

        function flushReview(cur: { no?: number; keyword?: string; response?: string }) {
          if (cur.keyword?.trim() && cur.response?.trim()) {
            reviewItems.push({ no: cur.no, keyword: cur.keyword.trim(), response: cur.response.trim() })
          }
        }

        if (qaSheetName) {
          const sheet = wb.Sheets[qaSheetName]
          const rows = XLSX.utils.sheet_to_json<unknown[]>(sheet, { header: 1 })
          let current: { no?: number; q?: string; a?: string } = {}
          for (const row of rows) {
            const a = String((row as unknown[])[0] ?? '').trim()
            const b = String((row as unknown[])[1] ?? '').trim()

            if (!a) {
              flushQA(current)
              current = {}
              continue
            }

            const noMatch = a.match(/^序号\s*(\d+)$/)
            if (noMatch) {
              flushQA(current)
              current = { no: parseInt(noMatch[1], 10) }
              continue
            }

            const qMatch = a.match(/^Q[：:]\s*$/)
            if (qMatch) {
              current.q = b
              continue
            }

            const aMatch = a.match(/^A[：:]\s*$/)
            if (aMatch) {
              current.a = b
              continue
            }
          }
          flushQA(current)
        }

        if (reviewSheetName) {
          const sheet = wb.Sheets[reviewSheetName]
          const rows = XLSX.utils.sheet_to_json<unknown[]>(sheet, { header: 1 })
          let current: { no?: number; keyword?: string; response?: string } = {}
          for (const row of rows) {
            const a = String((row as unknown[])[0] ?? '').trim()
            const b = String((row as unknown[])[1] ?? '').trim()

            if (!a) {
              flushReview(current)
              current = {}
              continue
            }

            const noMatch = a.match(/^序号\s*(\d+)$/)
            if (noMatch) {
              flushReview(current)
              current = { no: parseInt(noMatch[1], 10) }
              continue
            }

            const kwMatch = a.match(/^差评词[：:]\s*$/)
            if (kwMatch) {
              current.keyword = b
              continue
            }

            const respMatch = a.match(/^话术[：:]\s*$/)
            if (respMatch) {
              current.response = b
              continue
            }
          }
          flushReview(current)
        }

        resolve({ sku, fileName: file.name, qaItems, reviewItems, raw: { qa: qaItems, review: reviewItems } })
      } catch (err) {
        reject(err)
      }
    }
    reader.onerror = () => reject(new Error('文件读取失败'))
    reader.readAsArrayBuffer(file)
  })
}

// ── Field comparison for import preview ──────────────────────────

export function compareFields(oldData: ImportProductData, newData: ImportProductData): string[] {
  const diff: string[] = []
  const fields: (keyof ImportProductData)[] = [
    'sku', 'product_name_cn', 'product_name_en', 'barcode', 'brand', 'series',
    'category', 'product_level', 'launch_date', 'lifecycle_status', 'person_in_charge',
  ]
  for (const f of fields) {
    if (String(oldData[f] ?? '') !== String(newData[f] ?? '')) {
      diff.push(f)
    }
  }
  if (JSON.stringify(oldData.specs_data) !== JSON.stringify(newData.specs_data)) {
    diff.push('specs_data')
  }
  if (JSON.stringify(oldData.business_data) !== JSON.stringify(newData.business_data)) {
    diff.push('business_data')
  }
  if (JSON.stringify(oldData.content_data) !== JSON.stringify(newData.content_data)) {
    diff.push('content_data')
  }
  return diff
}
