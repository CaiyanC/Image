import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'
import { readFile } from 'node:fs/promises'

const bundle = await build({
  entryPoints: [fileURLToPath(new URL('../src/pages/assetLibraryHelpers.ts', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false,
  define: { 'import.meta.env': '{}' },
})
const loaded = { exports: {} }
new Function('require', 'module', 'exports', bundle.outputFiles[0].text)(createRequire(import.meta.url), loaded, loaded.exports)
const { addTag, removeTag, areExclusiveTags, changedAssetFields, getEffectiveAssetTags } = loaded.exports

const configBundle = await build({
  entryPoints: [fileURLToPath(new URL('../src/pages/assetLibraryConfig.ts', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false,
})
const configModule = { exports: {} }
new Function('require', 'module', 'exports', configBundle.outputFiles[0].text)(createRequire(import.meta.url), configModule, configModule.exports)
const { getUploadGuidelines } = configModule.exports

const apiBundle = await build({
  entryPoints: [fileURLToPath(new URL('../src/services/api.ts', import.meta.url))],
  bundle: true, platform: 'node', format: 'cjs', write: false,
  define: { 'import.meta.env': '{}' },
})
const apiModule = { exports: {} }
new Function('require', 'module', 'exports', apiBundle.outputFiles[0].text)(createRequire(import.meta.url), apiModule, apiModule.exports)
const { api } = apiModule.exports

const pageSource = await readFile(new URL('../src/pages/AssetLibrary.tsx', import.meta.url), 'utf8')
const pageBundle = await build({
  stdin: { contents: pageSource + `
    import React from 'react';
    import { renderToStaticMarkup } from 'react-dom/server';
    export function renderAssetEdit(asset, canReview, error='', taxonomyCategories=undefined) {
      return renderToStaticMarkup(React.createElement(EditModal, {
        asset, form: asset, canReview, error, qualityStatuses:['usable'], duplicateStatuses:['unique'],
        reviewStatuses:['pending','approved','rejected'], authorizationStatuses:['unknown','approved','authorized'],
        taxonomyCategories,
        setForm:()=>{}, onClose:()=>{}, onSave:()=>{},
      }));
    }`, loader: 'tsx', resolveDir: fileURLToPath(new URL('../src/pages/', import.meta.url)) },
  bundle: true, platform: 'node', format: 'cjs', packages: 'external', write: false,
  define: { 'import.meta.env': '{}' }, jsx: 'automatic',
})
const pageModule = { exports: {} }
new Function('require', 'module', 'exports', pageBundle.outputFiles[0].text)(createRequire(import.meta.url), pageModule, pageModule.exports)
const { renderAssetEdit } = pageModule.exports

test('review change replaces only the same criterion and preserves technical metadata', () => {
  const original = { quality_check_tags: ['完整性需修改', '质感通过'], subject_tags: ['主体'], video_duration_seconds: ['12'] }
  const changed = addTag(original, 'quality_check_tags', '完整性通过')
  assert.deepEqual(changed.quality_check_tags, ['质感通过', '完整性通过'])
  assert.deepEqual(changed.video_duration_seconds, ['12'])
  assert.deepEqual(original.quality_check_tags, ['完整性需修改', '质感通过'])
  assert.deepEqual(addTag(changed, 'quality_check_tags', '完整性通过'), changed)
  assert.deepEqual(addTag({ quality_check_tags: ['完整性通过', '完整性需修改'] }, 'quality_check_tags', '完整性通过').quality_check_tags, ['完整性通过'])
})

test('single-select dimensions replace while subject supports multiple objects', () => {
  assert.deepEqual(addTag({ view_tags: ['正视'] }, 'view_tags', '侧视').view_tags, ['侧视'])
  assert.deepEqual(addTag({ composition_tags: ['带人物'] }, 'composition_tags', '纯产品').composition_tags, ['纯产品'])
  assert.deepEqual(addTag({ subject_tags: ['主体'] }, 'subject_tags', '配件').subject_tags, ['主体', '配件'])
  assert.equal(areExclusiveTags('quality_check_tags', '完整性通过', '完整性需修改'), true)
  assert.equal(areExclusiveTags('quality_check_tags', '质感通过', '完整性需修改'), false)
})

test('legacy expressions replace only conflicting composition and removal preserves unrelated tags', () => {
  const result = addTag({ expression_tags: ['场景图', '人物场景图'] }, 'expression_tags', '纯产品场景图')
  assert.deepEqual(result.expression_tags, ['场景图', '纯产品场景图'])
  assert.deepEqual(removeTag({ subject_tags: ['配件'], view_tags: ['正视'] }, 'subject_tags', '配件'), { view_tags: ['正视'] })
})

test('editing a legacy asset submits only changed fields', () => {
  const original = { category_code: '05', category_name: '渠道销售图', sub_category: 'Amazon', material_type: 'amazonMain', maintainer: null, tags: { channel_tags: ['Amazon'] } }
  assert.deepEqual(changedAssetFields(original, { ...original, maintainer: '视觉维护人' }), { maintainer: '视觉维护人' })
})

test('legacy asset classification is visible to the same tag filters', () => {
  const tags = getEffectiveAssetTags({
    category_code: '01', sub_category: '多角度图', material_type: 'front',
    tags: {}, channel: 'Amazon',
  })
  assert.deepEqual(tags.material_type_tags, ['多角度图'])
  assert.deepEqual(tags.view_tags, ['正视'])
  assert.deepEqual(tags.channel_tags, ['Amazon'])
})

test('legacy scene classification stays separate from material-form tags', () => {
  const tags = getEffectiveAssetTags({ category_code: '04', sub_category: '森林', material_type: 'forest', tags: {} })
  assert.deepEqual(tags.scene_tags, ['森林'])
  assert.equal(tags.material_type_tags, undefined)
})

test('scene upload guidance uses the independent composition field instead of legacy expressions', () => {
  const guidance = getUploadGuidelines('04').join('\n')
  assert.match(guidance, /人物构成/)
  assert.match(guidance, /带人物/)
  assert.match(guidance, /纯产品/)
  assert.doesNotMatch(guidance, /人物场景图|纯产品场景图/)
})

test('asset upload page exposes multi-channel metadata separately from business grouping', () => {
  assert.match(pageSource, /适用渠道（可多选）/)
  assert.match(pageSource, /第一个渠道同时作为兼容旧素材的主渠道/)
  assert.match(pageSource, /channel_tags: uploadChannels/)
  assert.match(pageSource, /其他归属分类（可多选）/)
  assert.match(pageSource, /category_tags: categoryTags/)
})

test('asset tag controls are collapsed by default to keep the library compact', () => {
  assert.match(pageSource, /<details className="rounded-xl border border-teal-100 bg-teal-50\/45 p-3">\s*<summary[^>]*>[\s\S]*筛选已有素材（标签可多选）/)
  assert.match(pageSource, /<details className="mt-4 border-t border-teal-100 pt-4">\s*<summary[^>]*>[\s\S]*上传新图片时设置归属与标签（可选，不填也能上传）/)
  assert.match(pageSource, /点击展开 \/ 收起/)
})

test('asset upload request transmits every selected scene environment and channel', async () => {
  let submitted
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (_url, options) => {
    submitted = options.body
    return { ok: true, status: 200, json: async () => ({ count: 1, items: [] }) }
  }
  try {
    await api.assets.upload('CW-C95', {
      files: [new File([new Uint8Array([1])], 'scene.png', { type: 'image/png' })],
      category_code: '04', category_name: '场景内容图',
      category_tags: ['01/白底图', '05/国内电商'],
      scene_tags: ['森林', '湖边'],
      channel_tags: ['Amazon', '天猫'],
    })
  } finally {
    globalThis.fetch = previousFetch
  }
  assert.ok(submitted instanceof FormData)
  assert.deepEqual(submitted.getAll('category_tags'), ['01/白底图', '05/国内电商'])
  assert.deepEqual(submitted.getAll('scene_tags'), ['森林', '湖边'])
  assert.deepEqual(submitted.getAll('channel_tags'), ['Amazon', '天猫'])
})

test('asset search request transmits quality checks, maintainer, review and authorization filters', async () => {
  let requestedUrl = ''
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (url) => {
    requestedUrl = String(url)
    return { ok: true, status: 200, json: async () => ({ items: [] }) }
  }
  try {
    await api.assets.search({
      quality_check_tags: ['完整性通过', '完整性需修改'],
      maintainer: '视觉设计师', review_status: 'approved', authorization_status: 'authorized',
      is_public: false, ai_customer_usable: true,
    })
  } finally {
    globalThis.fetch = previousFetch
  }
  const query = new URL(requestedUrl, 'http://localhost').searchParams
  assert.deepEqual(query.getAll('quality_check_tags'), ['完整性通过', '完整性需修改'])
  assert.equal(query.get('maintainer'), '视觉设计师')
  assert.equal(query.get('review_status'), 'approved')
  assert.equal(query.get('authorization_status'), 'authorized')
  assert.equal(query.get('is_public'), 'false')
  assert.equal(query.get('ai_customer_usable'), 'true')
  assert.match(await readFile(new URL('../src/pages/AssetSearch.tsx', import.meta.url), 'utf8'), /已开启范围/)
})

test('real edit modal exposes domestic and cross-border placements separately', () => {
  const base = { category_code: '05', asset_type: 'video', material_type: 'mainImage' }
  const domestic = renderAssetEdit({ ...base, sub_category: '国内电商' }, true)
  const crossBorder = renderAssetEdit({ ...base, sub_category: '跨境电商' }, true)
  assert.match(domestic, /value="detailPage"/)
  assert.doesNotMatch(domestic, /value="aPlus"/)
  assert.match(crossBorder, /value="aPlus"/)
  assert.doesNotMatch(crossBorder, /value="detailPage"/)
})

test('edit modal consumes the backend category hierarchy when available', () => {
  const html = renderAssetEdit(
    { category_code: '05', sub_category: '后端定义分类', asset_type: 'image', material_type: 'serverDefined' },
    true,
    '',
    [{ code: '05', name: '电商与品牌图', sub_categories: [{ name: '后端定义分类', material_type: 'serverDefined' }] }],
  )
  assert.match(html, /后端定义分类/)
  assert.doesNotMatch(html, /历史值，保留/)
  assert.match(pageSource, /taxonomyCategories\.length/)
})

test('real edit modal preserves unknown categories and restricts review controls', () => {
  const html = renderAssetEdit({ category_code: '01', sub_category: '历史自定义', asset_type: 'video' }, false, '分类校验失败')
  assert.match(html, /历史自定义（历史值，保留）/)
  assert.match(html, /素材维护人/)
  assert.match(html, /role="alert"/)
  assert.match(html, /分类校验失败/)
  assert.match(html, /仅可由具备素材审核权限/)
  assert.doesNotMatch(html, /重复源素材 ID/)
})

test('reviewer edit modal exposes authorization and independent usage scopes', () => {
  const html = renderAssetEdit({
    category_code: '01', sub_category: '白底图', asset_type: 'image',
    review_status: 'approved', authorization_status: 'authorized',
    is_public: true, ai_customer_usable: true, ai_marketing_usable: false, ai_reference_usable: true,
  }, true)
  assert.match(html, /审核结论/)
  assert.match(html, /使用授权/)
  assert.match(html, /允许对外公开/)
  assert.match(html, /允许智能客服使用/)
  assert.match(html, /允许 AI 营销使用/)
  assert.match(html, /允许作为 AI 参考素材/)
  assert.match(html, /approved\/authorized/)
})
