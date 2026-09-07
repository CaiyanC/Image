// Run with: node tests/auth-permissions.cjs (no browser or API required).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const compiled = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/store/authStore.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const exported = {};
vm.runInNewContext(compiled, {
  exports: exported,
  require: (name) => {
    if (name === 'zustand') return { create: (initialize) => {
      let state;
      state = initialize((update) => Object.assign(state, update), () => state);
      return { getState: () => state };
    } };
    if (name === '../services/api') return { api: {}, ApiRequestError: class extends Error {} };
    throw Error(`Unexpected dependency: ${name}`);
  },
});
const user = (permissions = [], groups = []) => ({ id: 'test', username: 'test', permissions, groups });
assert.equal(exported.isManagement(null), false);
assert.equal(exported.isManagement(user(['system.admin'])), false);
assert.equal(exported.getLandingPath(user(['system.admin'])), '/no-access');
assert.equal(exported.hasPermission(user(['system.admin']), 'product.delete'), false);
for (const group_name of ['总经办', 'IT部', '产品部']) {
  for (const group_role of ['admin', 'member']) {
    assert.equal(exported.isManagement(user([], [{ group_name, group_role }])),
      group_name !== '产品部' && group_role === 'admin');
  }
}
const paths = {
  'ai.generate': '/', 'ai.customer_service': '/customer-service', 'tools.view': '/tools',
  'finance.ecommerce_data_fill': '/tools/ecommerce-data-fill', 'product.read': '/products',
  'product.qa.manage': '/products/qa/new', 'product.edit': '/products/qa/new',
  'product.create': '/products/create', 'product.audit.view': '/products/audit',
  'product.full.view': '/products/full-view', 'media.read': '/assets', 'media.search': '/assets/search',
  'knowledge.manage': '/knowledge-base', 'knowledge.files.manage': '/file-knowledge',
  'history.view': '/history', 'profile.view': '/profile',
};
for (const [permission, route] of Object.entries(paths)) assert.equal(exported.getLandingPath(user([permission])), route);
assert.equal(exported.getLandingPath(user()), '/no-access');
const state = exported.useAuthStore.getState();
state.setAuth(user(['system.admin']));
assert.equal(state.isManagement, false);
state.updateUser(user(['system.admin'], [{ group_name: 'IT部', group_role: 'admin' }]));
assert.equal(state.isManagement, true);
state.updateUser(user(['system.admin'], [{ group_name: 'IT部', group_role: 'member' }]));
assert.equal(state.isManagement, false);
state.clearAuth();
assert.equal(state.authenticated, false);
assert.equal(state.user, null);
console.log('32 authorization/landing/session assertions passed');
