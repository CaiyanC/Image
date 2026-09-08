import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'

// Exercise the actual persistence helpers, without exposing them in the app API.
const source = await readFile(new URL('../src/pages/CustomerService.tsx', import.meta.url), 'utf8')
const names = ['customerServiceDraftKey','createConversationState','saveCustomerServiceDraft','loadCustomerServiceDraft','restoreConversationStates','registerInFlightCustomerServiceRequest','removeInFlightCustomerServiceRequest']
const bundle = await build({
  stdin: { contents: source + `\nexport {${names.join(',')}}`, loader:'tsx', resolveDir:fileURLToPath(new URL('../src/pages/',import.meta.url)) },
  bundle:true, platform:'node', format:'cjs', packages:'external', write:false,
  define:{'import.meta.env':JSON.stringify({MODE:'dev'})},
})
const module = {exports:{}}
new Function('require','module','exports',bundle.outputFiles[0].text)(createRequire(import.meta.url),module,module.exports)
const api = module.exports
const storage = new Map()
globalThis.localStorage = {getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)}

test('unsent question and messages survive saving and restoration', () => {
  const key=api.customerServiceDraftKey('alice')
  const state=api.createConversationState({question:'这个锅能用电磁炉吗',messages:[{id:'1',role:'user',content:'KD23'}]})
  api.saveCustomerServiceDraft(key,{version:2,activeConversationKey:'local:1',conversationStates:{'local:1':state}})
  const restored=api.restoreConversationStates(api.loadCustomerServiceDraft(key).conversationStates,key)['local:1']
  assert.equal(restored.question,state.question)
  assert.equal(restored.messages[0].content,state.messages[0].content)
  assert.equal(restored.messages[0].streaming,false)
  assert.equal(api.loadCustomerServiceDraft(api.customerServiceDraftKey('bob')),null)
})

test('route restoration attaches to the live request without aborting it', () => {
  const key=api.customerServiceDraftKey('live-user')
  const controller=new AbortController()
  const state=api.createConversationState({loading:true,question:'下一条草稿',messages:[{id:'2',role:'assistant',content:'回复中',streaming:true}]})
  api.registerInFlightCustomerServiceRequest(key,'live',controller,state,'live')
  const restored=api.restoreConversationStates({live:state},key).live
  assert.equal(restored.loading,true)
  assert.equal(restored.abortController,controller)
  assert.equal(controller.signal.aborted,false)
  assert.equal(restored.messages[0].streaming,true)
  api.removeInFlightCustomerServiceRequest(key,'live')
  assert.equal(api.restoreConversationStates({live:state},key).live.loading,false)
})
