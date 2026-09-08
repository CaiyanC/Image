import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'

// Render real components without starting a server or signing into any account.
const bundle = await build({
  stdin: { contents: `
    import React from 'react';
    import {renderToStaticMarkup} from 'react-dom/server';
    import {MemoryRouter} from 'react-router-dom';
    import Header from './src/components/layout/Header';
    import SectionNavigation from './src/components/layout/SectionNavigation';
    import BusinessSidebar from './src/components/layout/BusinessSidebar';
    import ProductLookup from './src/components/ProductLookup';
    import {useAuthStore} from './src/store/authStore';
    export function render(path, permissions, management=false) {
      useAuthStore.setState({user:{username:'test',permissions,groups:[]},isManagement:management});
      return renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:[path]},
        React.createElement(React.Fragment,null,React.createElement(Header),React.createElement(BusinessSidebar),React.createElement(SectionNavigation),React.createElement(ProductLookup))));
    }`, resolveDir: fileURLToPath(new URL('../', import.meta.url)), loader: 'tsx' },
  bundle: true, platform: 'node', format: 'cjs', packages: 'external', write: false,
  plugins: [{ name: 'static-auth-fixture', setup(build) {
    build.onLoad({filter: /[\\/]store[\\/]authStore\.ts$/}, () => ({loader:'ts', contents: `
      let state = {};
      export const useAuthStore = (selector) => selector ? selector(state) : state;
      useAuthStore.setState = (next) => {state = next};
      export const hasPermission = (user, key) => !!user?.permissions?.includes(key);
      export const getLandingPath = () => '/no-access';
    `}));
  }}],
  define: { 'import.meta.env': JSON.stringify({MODE:'dev'}) },
})
const module = { exports: {} }
new Function('require', 'module', 'exports', bundle.outputFiles[0].text)(createRequire(import.meta.url), module, module.exports)
const {render} = module.exports
test('history and finance have explicit back links even with single permission', () => {
  assert.ok(render('/history', ['history.view']).includes('← 工具中心'))
  assert.ok(render('/tools/ecommerce-data-fill', ['finance.ecommerce_data_fill']).includes('← 工具中心'))
})
test('product maintenance is collapsed while parent link remains authorized', () => {
  const html = render('/products/edit/KD23-MFL', ['product.read','product.edit','product.audit.view'])
  assert.ok(html.includes('← 产品资料'))
  assert.ok(html.includes('<details'))
  assert.ok(html.includes('资料维护'))
  assert.ok(!html.includes('<details open'))
  assert.ok(!render('/products/edit/KD23-MFL', ['product.edit']).includes('← 产品资料'))
})
test('real asset header groups browsing and search under one center', () => {
  const html = render('/assets/search', ['media.read','media.search'])
  assert.ok(html.includes('素材中心内导航'))
  assert.ok(html.includes('浏览与管理'))
  assert.ok(html.includes('搜索素材'))
  assert.ok(html.includes('aria-current="page"'))
})
test('search-only account never receives media-read navigation', () => {
  const html = render('/assets/search', ['media.search'])
  assert.ok(html.includes('href="/tools"'))
  assert.ok(!html.includes('href="/assets"'))
})
test('finance-only account retains a working tool-center destination', () => {
  const html = render('/tools/ecommerce-data-fill', ['finance.ecommerce_data_fill'])
  assert.ok(html.includes('href="/tools"'))
  assert.ok(html.includes('href="/tools/ecommerce-data-fill"'))
})
test('sidebar exposes authorized primary functions without a tool-center detour', () => {
  const html = render('/tools', ['tools.view','finance.ecommerce_data_fill','media.read','product.read','ai.generate','ai.customer_service'])
  for (const path of ['/products','/assets','/customer-service','/tools/ecommerce-data-fill']) assert.ok(html.includes(`href="${path}"`))
  assert.ok(html.includes('href="/tools"'))
})
test('ordinary customer service user does not see experimental chain', () => {
  const html = render('/customer-service', ['ai.customer_service'])
  assert.ok(!html.includes('Agent'))
  assert.ok(!html.includes('客服实验室'))
})
test('knowledge-only delegate receives a business entry, not system administration', () => {
  assert.ok(render('/knowledge-base', ['knowledge.manage']).includes('href="/knowledge-base"'))
  assert.ok(!render('/knowledge-base', ['knowledge.manage']).includes('系统管理'))
  assert.ok(!render('/no-access', []).includes('系统管理'))
})

test('product lookup is hidden without product read, and distinguishes detail permission', () => {
  assert.ok(!render('/customer-service', ['ai.customer_service']).includes('aria-label="查产品"'))
  assert.ok(render('/customer-service', ['product.read']).includes('aria-label="查产品"'))
  assert.ok(render('/customer-service', ['product.read']).includes('完整参数需要产品详情权限'))
  assert.ok(!render('/customer-service', ['product.read','product.edit']).includes('完整参数需要产品详情权限'))
})
