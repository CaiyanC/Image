import test from 'node:test'
import assert from 'node:assert/strict'
import { backEntry, businessLandingPath, sectionForPath, sections, visibleSections, supplementalEntries } from '../src/components/layout/navigation.ts'

const visible = permissions => visibleSections(key => permissions.includes(key))
test('back links use authorized parents, never browser history', () => {
  assert.equal(backEntry('/history', () => false), null)
  assert.deepEqual(backEntry('/products/edit/SKU', key => key === 'product.read'), {path:'/products', label:'知识库'})
  assert.equal(backEntry('/products/create', () => false), null)
  assert.equal(backEntry('/tools', () => true), null)
})
test('all grants produce only three business centers', () => {
  const grants = sections.flatMap(s => s.items.flatMap(i => i.permissions))
  assert.equal(visible(grants).length, 3)
  assert.deepEqual(visible(grants).map(s => s.label), ['知识库', '智能客服', '素材库'])
  assert.equal(visible(grants)[0].items[0].path, '/products')
})
test('no grants expose no business links', () => assert.deepEqual(visible([]), []))
for (const grant of [...new Set(sections.flatMap(s => s.items.flatMap(i => i.permissions)))]) {
  test(`single grant ${grant} retains an accessible entry and no unauthorized child`, () => {
    const result = visible([grant])
    assert.ok(result.length > 0)
    for (const section of result) for (const item of section.items) assert.ok(item.permissions.includes(grant))
  })
}
test('search-only and full-view-only accounts retain direct entry', () => {
  for (const [grant, path] of [['media.search','/assets/search'],['product.full.view','/products/full-view']]) {
    assert.equal(visible([grant])[0].items[0].path, path)
  }
})
test('nested and legacy URLs keep their business center active', () => {
  for (const [path, key] of [['/products/edit/KD23-MFL','products'],['/products/create/draft-id','products'],['/assets/search','assets'],['/knowledge-base','products'],['/file-knowledge','products'],['/customer-service/agent','customer']]) assert.equal(sectionForPath(path), key)
  assert.equal(sectionForPath('/products-other'), undefined)
  assert.equal(sectionForPath('/admin/access-control'), undefined)
})
test('revocation removes links immediately on recomputation', () => {
  assert.equal(visible(['media.read','media.search'])[0].items.length, 2)
  assert.deepEqual(visible(['media.search'])[0].items.map(i => i.path), ['/assets/search'])
})
test('competitor entry is visible only with competitor or upload access', () => {
  assert.deepEqual(visible(['competitor.view'])[0].items.map(item => item.path), ['/assets/competitors'])
  assert.deepEqual(visible(['media.upload'])[0].items.map(item => item.path), ['/assets/competitors'])
  assert.equal(visible(['media.read']).some(section => section.items.some(item => item.path === '/assets/competitors')), false)
  assert.equal(sectionForPath('/assets/competitors'), 'assets')
})
test('sub-feature-only users receive an authorized card without duplicate primary cards', () => {
  for (const [permission, path] of [['media.search','/assets/search'],['knowledge.files.manage','/file-knowledge'],['product.full.view','/products/full-view'],['product.qa.manage','/products/qa/new']]) {
    assert.equal(supplementalEntries(key => key === permission)[0].path, path)
  }
  assert.deepEqual(supplementalEntries(() => false), [])
  assert.deepEqual(supplementalEntries(() => true), [])
})

test('retired grants cannot restore links or a retired landing path', () => {
  for (const permission of ['finance.ecommerce_data_fill', 'ai.generate', 'history.view', 'tools.view']) {
    const has = key => key === permission
    assert.deepEqual(visibleSections(has), [])
    assert.equal(businessLandingPath(has), '/no-access')
  }
  assert.equal(businessLandingPath(() => true), '/customer-service')
  assert.equal(sectionForPath('/tools/ecommerce-data-fill'), undefined)
  assert.equal(sectionForPath('/history'), undefined)
})
