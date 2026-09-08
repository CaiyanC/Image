import test from 'node:test'
import assert from 'node:assert/strict'
import { backEntry, sectionForPath, sections, visibleSections, supplementalEntries } from '../src/components/layout/navigation.ts'

const visible = permissions => visibleSections(key => permissions.includes(key))
test('back links use authorized parents, never browser history', () => {
  assert.deepEqual(backEntry('/history', () => false), {path:'/tools', label:'工具中心'})
  assert.deepEqual(backEntry('/products/edit/SKU', key => key === 'product.read'), {path:'/products', label:'产品资料'})
  assert.deepEqual(backEntry('/products/create', () => false), {path:'/tools', label:'工具中心'})
  assert.equal(backEntry('/tools', () => true), null)
})
test('all grants produce five business centers without duplicate top-level entries', () => {
  const grants = sections.flatMap(s => s.items.flatMap(i => i.permissions))
  assert.equal(visible(grants).length, 5)
  assert.equal(new Set(visible(grants).map(s => s.key)).size, 5)
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
test('finance-only, search-only and full-view-only accounts retain direct entry', () => {
  for (const [grant, path] of [['finance.ecommerce_data_fill','/tools/ecommerce-data-fill'],['media.search','/assets/search'],['product.full.view','/products/full-view']]) {
    assert.equal(visible([grant])[0].items[0].path, path)
  }
})
test('nested and legacy URLs keep their business center active', () => {
  for (const [path, key] of [['/products/edit/KD23-MFL','products'],['/products/create/draft-id','products'],['/assets/search','assets'],['/tools/ecommerce-data-fill','tools'],['/customer-service/agent','customer'],['/history','creation']]) assert.equal(sectionForPath(path), key)
  assert.equal(sectionForPath('/products-other'), undefined)
  assert.equal(sectionForPath('/admin/access-control'), undefined)
})
test('revocation removes links immediately on recomputation', () => {
  assert.equal(visible(['media.read','media.search'])[0].items.length, 2)
  assert.deepEqual(visible(['media.search'])[0].items.map(i => i.path), ['/assets/search'])
})
test('sub-feature-only users receive an authorized card without duplicate primary cards', () => {
  for (const [permission, path] of [['media.search','/assets/search'],['history.view','/history'],['product.full.view','/products/full-view'],['product.qa.manage','/products/qa/new']]) {
    assert.equal(supplementalEntries(key => key === permission)[0].path, path)
  }
  assert.deepEqual(supplementalEntries(() => false), [])
  assert.deepEqual(supplementalEntries(() => true), [])
})
