import test from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const bundle = await build({
  stdin: { contents: `
    import React from 'react';
    import { renderToStaticMarkup } from 'react-dom/server';
    import CompetitorLibrary from './src/pages/CompetitorLibrary';
    import { useAuthStore } from './src/store/authStore';
    export function render(permissions) {
      useAuthStore.setState({ user: { permissions } });
      return renderToStaticMarkup(React.createElement(CompetitorLibrary));
    }
  `, loader: 'tsx', resolveDir: fileURLToPath(new URL('../', import.meta.url)) },
  bundle: true, platform: 'node', format: 'cjs', packages: 'external', write: false,
  define: { 'import.meta.env': '{}' }, jsx: 'automatic',
  plugins: [{ name: 'auth-fixture', setup(builder) {
    builder.onLoad({ filter: /[\\/]store[\\/]authStore\.ts$/ }, () => ({ loader: 'ts', contents: `
      let state = {};
      export const useAuthStore = () => state;
      useAuthStore.setState = value => { state = value };
      useAuthStore.getState = () => state;
      useAuthStore.subscribe = () => () => {};
      export const hasPermission = (user, key) => !!user?.permissions?.includes(key);
    ` }));
  } }],
})
const loaded = { exports: {} }
new Function('require', 'module', 'exports', bundle.outputFiles[0].text)(createRequire(import.meta.url), loaded, loaded.exports)
const { render } = loaded.exports

test('viewer can see brand browsing but not upload form', () => {
  const html = render(['competitor.view'])
  assert.match(html, /竞品素材中心/)
  assert.match(html, /请选择品牌/)
  assert.doesNotMatch(html, /type="file"/)
  assert.doesNotMatch(html, /上传内部参考素材/)
})

test('curator sees independently defined fields and file type choices', () => {
  const html = render(['media.upload'])
  for (const label of ['竞品品牌', '素材维护人', '来源说明', '素材形式', '仅供内部参考', '不授予对外发布或 AI 使用权限']) assert.ok(html.includes(label), label)
  assert.match(html, /type="file"/)
  assert.match(html, /accept="\.jpg,\.jpeg,\.png,\.webp,\.gif"/)
  assert.match(html, /value="image"/)
  assert.match(html, /value="video"/)
  assert.doesNotMatch(html, /name="sku"/)
})
