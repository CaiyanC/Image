const XLSX = require('../frontend/node_modules/xlsx')
const fs = require('fs')
const path = require('path')

function getCell(row, colIndex) {
  if (colIndex < 0 || colIndex >= row.length) return ''
  const v = row[colIndex]
  if (v === null || v === undefined) return ''
  if (typeof v === 'number') {
    if (Number.isInteger(v) && v >= 1e10) {
      return String(v)
    }
    return String(v)
  }
  return String(v).trim()
}

function parseDate(raw) {
  if (raw === null || raw === undefined || raw === '') return ''
  if (typeof raw === 'number' && raw > 40000 && raw < 80000) {
    const date = new Date((raw - 25569) * 86400 * 1000)
    const y = date.getUTCFullYear()
    const m = String(date.getUTCMonth() + 1).padStart(2, '0')
    const d = String(date.getUTCDate()).padStart(2, '0')
    return `${y}-${m}-${d}`
  }
  const s = String(raw).trim()
  const m = s.match(/(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})/)
  if (m) return `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`
  return s
}

function parseMultilineToArray(raw) {
  if (!raw) return []
  return String(raw).split(/\n+/).map(l => l.replace(/^\d+[\.\、\)]\s*/, '').trim()).filter(Boolean)
}

function parseCommaSeparated(raw) {
  if (!raw) return []
  return String(raw).split(/[\n,，、]+/).map(s => s.trim()).filter(Boolean)
}

function parseDimensionLines(raw) {
  if (!raw) return []
  const lines = String(raw).split(/\n+/).filter(Boolean)
  const result = []
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

function parseCapacityLines(raw) {
  if (!raw) return []
  const lines = String(raw).split(/\n+/).filter(Boolean)
  const result = []
  for (const line of lines) {
    const trimmed = line.trim()
    const m = trimmed.match(/^(\D+)(\d[\d.]*\s*[a-zA-Z]+.*)$/)
    if (m) {
      result.push({ label: m[1].trim(), value: m[2].trim() })
    } else {
      result.push({ label: '', value: trimmed })
    }
  }
  return result
}

function parsePowerWattage(raw) {
  if (!raw) return { min_power: '', max_power: '', power_wattage: '' }
  const text = String(raw).trim()
  const lines = text.split(/\n+/).filter(Boolean)
  let minPower = ''
  let maxPower = ''
  for (const line of lines) {
    const trimmed = line.trim()
    const minMatch = trimmed.match(/最小功率[：:]\s*(.+)/)
    if (minMatch) { minPower = minMatch[1].trim(); continue }
    const maxMatch = trimmed.match(/最大功率[：:]\s*(.+)/)
    if (maxMatch) { maxPower = maxMatch[1].trim(); continue }
    if (!minMatch && !maxMatch) { maxPower = trimmed }
  }
  return { min_power: minPower, max_power: maxPower, power_wattage: minPower ? `${minPower} ~ ${maxPower}` : maxPower }
}

function extractSkuFromFilename(filename) {
  const name = filename.replace(/\.xlsx?$/i, '')
  const sku = name.split('_')[0].trim()
  if (!sku) throw new Error('文件名格式不正确，无法提取SKU')
  return sku
}

const STOP_COLUMN = '搜索关键词库'
const COLUMNS = [
  '名称', 'SKU', '条形码', '商品中文名称', '商品英文名称',
  '上架渠道', '售卖地区', '品牌', '系列', '系统分类',
  '商品分级', '上市时间', '生命周期', '负责人',
  '尺寸信息', '容量信息', '毛重(g)', '主体材质', '主色系',
  '表面处理', '适用热源', '功率（炉具类）', '技术优势',
  '认证信息', '使用说明',
  '核心卖点 TOP5', '目标人群', '差异化定位', '价格定位带',
  '情感价值', '使用场景', '竞品对标',
  '标题（英文）', '标题（中文）', '产品长描述（英文）', '产品长描述（中文）',
  '搜索关键词库',
]

function parseL1L4(filePath) {
  const data = fs.readFileSync(filePath)
  const wb = XLSX.read(data, { type: 'buffer' })
  const sheetName = wb.SheetNames[0]
  const sheet = wb.Sheets[sheetName]
  const rows = XLSX.utils.sheet_to_json(sheet, { header: 1 })

  console.log(`Total rows in sheet: ${rows.length}`)

  if (rows.length < 6) {
    console.log('ERROR: Less than 6 rows')
    return []
  }

  const headerRow = rows[3]
  const colMap = {}
  let stopIndex = -1
  for (let i = 0; i < headerRow.length; i++) {
    const h = String(headerRow[i] || '').trim()
    colMap[h] = i
    if (h === STOP_COLUMN) stopIndex = i
  }

  const results = []
  for (let i = 5; i < rows.length; i++) {
    const row = rows[i]
    if (!row || row.length === 0) continue

    const sku = getCell(row, colMap['SKU'] ?? -1)
    console.log(`  Row ${i + 1}: SKU="${sku}"`)
    if (!sku) {
      console.log('    -> STOP (empty SKU)')
      break
    }

    const nameZh = getCell(row, colMap['商品中文名称'] ?? -1)
    const nameEn = getCell(row, colMap['商品英文名称'] ?? -1)
    const barcode = getCell(row, colMap['条形码'] ?? -1)
    const brand = getCell(row, colMap['品牌'] ?? -1)
    const series = getCell(row, colMap['系列'] ?? -1)
    const category = getCell(row, colMap['系统分类'] ?? -1)
    const grade = getCell(row, colMap['商品分级'] ?? -1)
    const launchDate = parseDate(row[colMap['上市时间'] ?? -1])
    const lifecycle = getCell(row, colMap['生命周期'] ?? -1)
    const personInCharge = getCell(row, colMap['负责人'] ?? -1)

    const listingChannel = parseCommaSeparated(getCell(row, colMap['上架渠道'] ?? -1))
    const salesRegion = parseCommaSeparated(getCell(row, colMap['售卖地区'] ?? -1))
    const dimensionLines = parseDimensionLines(getCell(row, colMap['尺寸信息'] ?? -1))
    const capacityLines = parseCapacityLines(getCell(row, colMap['容量信息'] ?? -1))
    const grossWeightRaw = getCell(row, colMap['毛重(g)'] ?? -1)
    const grossWeight = grossWeightRaw ? parseFloat(grossWeightRaw) || 0 : 0
    const material = getCell(row, colMap['主体材质'] ?? -1)
    const mainColor = getCell(row, colMap['主色系'] ?? -1)
    const surfaceFinish = getCell(row, colMap['表面处理'] ?? -1)
    const heatSourceRaw = getCell(row, colMap['适用热源'] ?? -1)
    const heatSource = heatSourceRaw ? parseMultilineToArray(heatSourceRaw).join(', ') : ''
    const powerData = parsePowerWattage(getCell(row, colMap['功率（炉具类）'] ?? -1))
    const techAdvantages = parseMultilineToArray(getCell(row, colMap['技术优势'] ?? -1))
    const certifications = parseMultilineToArray(getCell(row, colMap['认证信息'] ?? -1))
    const usageInstructions = getCell(row, colMap['使用说明'] ?? -1)
    const coreSellingPoints = parseMultilineToArray(getCell(row, colMap['核心卖点 TOP5'] ?? -1))
    const targetAudience = getCell(row, colMap['目标人群'] ?? -1)
    const differentiation = getCell(row, colMap['差异化定位'] ?? -1)
    const pricePositioning = getCell(row, colMap['价格定位带'] ?? -1)
    const emotionalValue = getCell(row, colMap['情感价值'] ?? -1)
    const useScenarios = parseMultilineToArray(getCell(row, colMap['使用场景'] ?? -1))
    const competitors = getCell(row, colMap['竞品对标'] ?? -1).split(/\n+/).map(s => s.trim()).filter(Boolean).map(name => ({ name }))
    const amazonTitle = getCell(row, colMap['标题（英文）'] ?? -1)
    const websiteTitle = getCell(row, colMap['标题（中文）'] ?? -1)
    const listingEn = getCell(row, colMap['产品长描述（英文）'] ?? -1)
    const listingZh = getCell(row, colMap['产品长描述（中文）'] ?? -1)
    const searchKeywordsRaw = getCell(row, colMap[STOP_COLUMN] ?? -1)
    const searchKeywords = []
    String(searchKeywordsRaw).split(/\n+/).map(s => s.trim()).filter(Boolean).forEach(line => {
      const m = line.match(/^([ABC])级[：:]\s*(.+)$/)
      if (m) {
        const priority = m[1]
        m[2].split(/[,，]+/).map(s => s.trim()).filter(Boolean).forEach(kw => {
          searchKeywords.push({ keyword: kw, priority })
        })
      }
    })

    results.push({ sku, name_zh: nameZh, name_en: nameEn, barcode, brand, series, category, grade, launch_date: launchDate, lifecycle, person_in_charge: personInCharge,
      specs_data: { dimension_lines: dimensionLines, capacity_lines: capacityLines, gross_weight: grossWeight, material, main_color: mainColor, surface_finish: surfaceFinish, heat_source: heatSource, power_wattage: powerData.power_wattage, min_power: powerData.min_power, max_power: powerData.max_power, tech_advantages: techAdvantages, certifications, usage_instructions: usageInstructions, sales_region: salesRegion },
      business_data: { core_selling_points: coreSellingPoints, target_audience: targetAudience, differentiation, price_positioning: pricePositioning, emotional_value: emotionalValue, use_scenarios: useScenarios, competitors, listing_channel: listingChannel },
      content_data: { amazon_title: amazonTitle, website_title: websiteTitle, listing_en: listingEn, listing_zh: listingZh, search_keywords: searchKeywords }
    })
  }

  return results
}

function parseL5(filePath) {
  const filename = path.basename(filePath)
  console.log(`\nFilename: ${filename}`)
  let sku
  try {
    sku = extractSkuFromFilename(filename)
    console.log(`  SKU extracted: ${sku}`)
  } catch (e) {
    console.log(`  SKU extraction FAILED: ${e.message}`)
    return null
  }

  const data = fs.readFileSync(filePath).buffer
  const wb = XLSX.read(data, { type: 'buffer' })

  // Sheet1: Q&A
  const qaItems = []
  if (wb.SheetNames[0]) {
    const sheet1 = wb.Sheets[wb.SheetNames[0]]
    const rows1 = XLSX.utils.sheet_to_json(sheet1, { header: 1 })
    let currentQA = {}
    for (const row of rows1) {
      const cells = row.map(c => String(c ?? '').trim())
      const combined = cells.join(' ').trim()
      if (!combined) {
        if (currentQA.q && currentQA.a) { qaItems.push({ q: currentQA.q, a: currentQA.a }) }
        currentQA = {}
        continue
      }
      const qMatch = combined.match(/Q[：:]\s*(.+)/)
      if (qMatch) {
        if (currentQA.q && currentQA.a) { qaItems.push({ q: currentQA.q, a: currentQA.a }) }
        currentQA = { q: qMatch[1].trim() }
      }
      const aMatch = combined.match(/A[：:]\s*(.+)/)
      if (aMatch) currentQA.a = aMatch[1].trim()
    }
    if (currentQA.q && currentQA.a) { qaItems.push({ q: currentQA.q, a: currentQA.a }) }
  }

  // Sheet2: Review
  const reviewItems = []
  if (wb.SheetNames[1]) {
    const sheet2 = wb.Sheets[wb.SheetNames[1]]
    const rows2 = XLSX.utils.sheet_to_json(sheet2, { header: 1 })
    let currentReview = {}
    for (const row of rows2) {
      const cells = row.map(c => String(c ?? '').trim())
      const combined = cells.join(' ').trim()
      if (!combined) {
        if (currentReview.keyword && currentReview.response) { reviewItems.push({ keyword: currentReview.keyword, response: currentReview.response }) }
        currentReview = {}
        continue
      }
      const kwMatch = combined.match(/差评词[：:]\s*(.+)/)
      if (kwMatch) {
        if (currentReview.keyword && currentReview.response) { reviewItems.push({ keyword: currentReview.keyword, response: currentReview.response }) }
        currentReview = { keyword: kwMatch[1].trim() }
      }
      const respMatch = combined.match(/话术[：:]\s*(.+)/)
      if (respMatch) currentReview.response = respMatch[1].trim()
    }
    if (currentReview.keyword && currentReview.response) { reviewItems.push({ keyword: currentReview.keyword, response: currentReview.response }) }
  }

  console.log(`  Q&A items: ${qaItems.length}`)
  console.log(`  Review items: ${reviewItems.length}`)
  return { sku, fileName: filename, qaItems, reviewItems }
}

// ====== RUN TESTS ======
console.log('='.repeat(60))
console.log('TEST 1: L1-L4 Excel Parsing')
console.log('='.repeat(60))
const l1l4Results = parseL1L4(path.join(__dirname, '..', 'test_files', 'L1L4_test_products.xlsx'))

console.log(`\nParsed ${l1l4Results.length} products:`)
const checks = []

for (const p of l1l4Results) {
  checks.push(`  ${p.sku}: name="${p.name_zh}" brand="${p.brand}" category="${p.category}" grade="${p.grade}" launch="${p.launch_date}" lifecycle="${p.lifecycle}"`)
  checks.push(`    specs: dim=${p.specs_data.dimension_lines.length} cap=${p.specs_data.capacity_lines.length} wt=${p.specs_data.gross_weight} mat=${p.specs_data.material} heat=${p.specs_data.heat_source} minP=${p.specs_data.min_power} maxP=${p.specs_data.max_power} fullP=${p.specs_data.power_wattage}`)
  checks.push(`    business: selling_pts=${p.business_data.core_selling_points.length} competitors=${p.business_data.competitors.length}`)
  checks.push(`    content: amazon="${p.content_data.amazon_title}" website="${p.content_data.website_title}" keywords=${p.content_data.search_keywords.length}`)
}
console.log(checks.join('\n'))

console.log('\n' + '='.repeat(60))
console.log('TEST 2: L5 Excel Parsing (valid file)')
console.log('='.repeat(60))
const l5Result = parseL5(path.join(__dirname, '..', 'test_files', 'CW-C01-01_product_knowledge.xlsx'))
if (l5Result) {
  l5Result.qaItems.forEach((qa, i) => console.log(`  QA${i + 1}: Q="${qa.q.substring(0, 30)}..." A="${qa.a.substring(0, 30)}..."`))
  l5Result.reviewItems.forEach((ri, i) => console.log(`  Review${i + 1}: keyword="${ri.keyword}" response="${ri.response.substring(0, 30)}..."`))
}

console.log('\n' + '='.repeat(60))
console.log('TEST 3: L5 Excel Parsing (BAD filename)')
console.log('='.repeat(60))
const l5Bad = parseL5(path.join(__dirname, '..', 'test_files', 'bad_filename_no_sku.xlsx'))

console.log('\n' + '='.repeat(60))
console.log('TEST 4: parseCommaSeparated with newlines')
console.log('='.repeat(60))
const csResult = parseCommaSeparated('淘宝\n京东\nAmazon')
console.log(`  Result: [${csResult.join(', ')}]`)
console.log(`  Expected: [淘宝, 京东, Amazon]`)
console.log(`  ${csResult.length === 3 && csResult[0] === '淘宝' ? '✅ PASS' : '❌ FAIL'}`)

console.log('\n' + '='.repeat(60))
console.log('TEST 5: parseDimensionLines without colons')
console.log('='.repeat(60))
const dimResult = parseDimensionLines('14*28.5 cm\n14*16.5 cm\n12.5*10 cm')
console.log(`  Parsed ${dimResult.length} lines:`)
dimResult.forEach(d => console.log(`    label="${d.label}" value="${d.value}" unit="${d.unit}"`))
console.log(`  ${dimResult.length === 3 ? '✅ PASS' : '❌ FAIL'}`)

console.log('\n' + '='.repeat(60))
console.log('TEST 6: parseDimensionLines with plain values')
console.log('='.repeat(60))
const dimResult2 = parseDimensionLines('硬质氧化铝合金\n不锈钢\n铜')
console.log(`  Parsed ${dimResult2.length} lines:`)
dimResult2.forEach(d => console.log(`    label="${d.label}" value="${d.value}" unit="${d.unit}"`))
console.log(`  ${dimResult2.length === 3 ? '✅ PASS' : '❌ FAIL'}`)

console.log('\n' + '='.repeat(60))
console.log('TEST 7: parseCommaSeparated mixed commas + newlines')
console.log('='.repeat(60))
const csResult2 = parseCommaSeparated('淘宝,京东\nAmazon\nEtsy')
console.log(`  Result: [${csResult2.join(', ')}]`)
console.log(`  ${csResult2.length === 4 ? '✅ PASS' : '❌ FAIL'}`)

console.log('\n' + '='.repeat(60))
console.log('TEST 8: parsePowerWattage (both min & max)')
console.log('='.repeat(60))
const pw1 = parsePowerWattage('最小功率：900W\n最大功率：3200W')
console.log(`  min_power="${pw1.min_power}" max_power="${pw1.max_power}" combined="${pw1.power_wattage}"`)
console.log(`  ${pw1.min_power === '900W' && pw1.max_power === '3200W' && pw1.power_wattage === '900W ~ 3200W' ? '✅ PASS' : '❌ FAIL'}`)

console.log('\n' + '='.repeat(60))
console.log('TEST 9: parsePowerWattage (max only)')
console.log('='.repeat(60))
const pw2 = parsePowerWattage('最大功率：2250W')
console.log(`  min_power="${pw2.min_power}" max_power="${pw2.max_power}" combined="${pw2.power_wattage}"`)
console.log(`  ${pw2.min_power === '' && pw2.max_power === '2250W' && pw2.power_wattage === '2250W' ? '✅ PASS' : '❌ FAIL'}`)

console.log('\n' + '='.repeat(60))
console.log('TEST 10: parsePowerWattage (legacy plain value)')
console.log('='.repeat(60))
const pw3 = parsePowerWattage('2000W')
console.log(`  min_power="${pw3.min_power}" max_power="${pw3.max_power}" combined="${pw3.power_wattage}"`)
console.log(`  ${pw3.min_power === '' && pw3.max_power === '2000W' && pw3.power_wattage === '2000W' ? '✅ PASS' : '❌ FAIL'}`)

console.log('\n' + '='.repeat(60))
console.log('TEST 11: parsePowerWattage (empty)')
console.log('='.repeat(60))
const pw4 = parsePowerWattage('')
console.log(`  min_power="${pw4.min_power}" max_power="${pw4.max_power}" combined="${pw4.power_wattage}"`)
console.log(`  ${pw4.min_power === '' && pw4.max_power === '' && pw4.power_wattage === '' ? '✅ PASS' : '❌ FAIL'}`)

console.log('\n✅ All tests complete!')
