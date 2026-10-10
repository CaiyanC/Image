import { useEffect, useRef, useState } from 'react'
import { api } from '../services/api'
import { SecureImage, SecureVideo } from '../components/SecureFile'
import { hasPermission, useAuthStore } from '../store/authStore'
import type { CompetitorAsset, CompetitorBrandCount } from '../types'
import { ASSET_UPLOAD_LIMITS } from './assetLibraryConfig'

export default function CompetitorLibrary() {
  const { user } = useAuthStore()
  const canUpload = hasPermission(user, 'media.upload')
  const [brands, setBrands] = useState<CompetitorBrandCount[]>([])
  const [brand, setBrand] = useState('')
  const [kind, setKind] = useState<'image' | 'video'>('image')
  const [items, setItems] = useState<CompetitorAsset[]>([])
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [uploadBrand, setUploadBrand] = useState('')
  const [uploadKind, setUploadKind] = useState<'image' | 'video'>('image')
  const [maintainer, setMaintainer] = useState('')
  const [source, setSource] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const [uploadMessage, setUploadMessage] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const [editing, setEditing] = useState<CompetitorAsset | null>(null)
  const [saving, setSaving] = useState(false)
  const [editError, setEditError] = useState('')

  const saveMetadata = async () => {
    if (!editing) return
    setSaving(true)
    setEditError('')
    try {
      const updated = await api.competitors.update(editing.id, { brand: editing.brand, maintainer: editing.maintainer, source_note: editing.source_note, notes: editing.notes })
      setBrand(updated.brand); setOffset(0); setRevision(value => value + 1); setEditing(null)
    } catch (reason) { setEditError(reason instanceof Error ? reason.message : '保存失败') }
    finally { setSaving(false) }
  }

  useEffect(() => {
    let active = true
    api.competitors.brands().then(result => { if (active) setBrands(result.items) })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '品牌列表读取失败') })
    return () => { active = false }
  }, [revision])

  useEffect(() => {
    let active = true
    if (!brand) return
    setLoading(true)
    setError('')
    setItems([])
    api.competitors.list(brand, kind, offset).then(result => { if (active) setItems(result.items) })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '素材读取失败') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [brand, kind, offset, revision])

  const upload = async () => {
    const limits = ASSET_UPLOAD_LIMITS[uploadKind]
    const normalizedBrand = uploadBrand.trim()
    setUploadMessage('')
    if (!normalizedBrand || !files.length) { setUploadMessage('请填写竞品品牌并选择文件'); return }
    if (files.length > limits.maxFiles || files.some(file => file.size > limits.maxBytes)) {
      setUploadMessage(`每批最多 ${limits.maxFiles} 个文件，单文件最多 ${limits.maxBytes / 1024 / 1024}MB`); return
    }
    setUploading(true)
    try {
      const result = await api.competitors.upload({ brand: normalizedBrand, asset_type: uploadKind, maintainer, source_note: source, files })
      setUploadMessage(`已保存 ${result.count} 项竞品参考素材；不代表已取得版权或发布许可`)
      setFiles([])
      if (inputRef.current) inputRef.current.value = ''
      setBrand(normalizedBrand)
      setKind(uploadKind)
      setOffset(0)
      setRevision(value => value + 1)
    } catch (reason) {
      setUploadMessage(reason instanceof Error ? reason.message : '上传失败，请重试')
    } finally { setUploading(false) }
  }

  return <main className="mx-auto max-w-6xl space-y-5 p-5">
    <header className="glass p-5"><h1 className="text-2xl font-black">竞品素材中心</h1>
      <p className="mt-2 text-sm text-stone-600">按竞品品牌收集图片和视频，不绑定本公司 SKU。仅供内部参考；来源备注不等于版权证明，不授予对外发布或 AI 使用权限。</p>
    </header>
    {canUpload && <section className="glass space-y-3 p-5">
      <h2 className="font-bold">上传参考素材</h2>
      <fieldset disabled={uploading} className="grid gap-3 sm:grid-cols-2">
        <label>竞品品牌<input className="glass-input mt-1 w-full p-2" maxLength={64} value={uploadBrand} onChange={event => setUploadBrand(event.target.value)} /></label>
        <label>素材维护人<input className="glass-input mt-1 w-full p-2" maxLength={100} value={maintainer} onChange={event => setMaintainer(event.target.value)} /></label>
        <label>素材形式<select className="glass-input mt-1 w-full p-2" value={uploadKind} onChange={event => {
          setUploadKind(event.target.value as 'image' | 'video'); setFiles([]); if (inputRef.current) inputRef.current.value = ''
        }}><option value="image">图片</option><option value="video">视频</option></select></label>
        <label>来源说明<input className="glass-input mt-1 w-full p-2" maxLength={2000} value={source} onChange={event => setSource(event.target.value)} /></label>
        <label className="sm:col-span-2">文件<input ref={inputRef} className="mt-1 block" type="file" multiple accept={uploadKind === 'image' ? '.jpg,.jpeg,.png,.webp,.gif' : '.mp4,.mov,.webm'} onChange={event => setFiles(Array.from(event.target.files || []))} /></label>
      </fieldset>
      <p className="text-xs text-stone-600">图片单文件 20MB、每批 20 张；视频单文件 200MB、每批 5 个。维护人负责收集更新，上传账号由系统单独记录。</p>
      <button disabled={uploading} className="rounded-full bg-teal-700 px-4 py-2 text-white disabled:opacity-50" onClick={() => void upload()}>{uploading ? '上传中…' : '上传内部参考素材'}</button>
      {uploadMessage && <p role="status" className="text-sm">{uploadMessage}</p>}
    </section>}
    <section className="glass space-y-4 p-5">
      <div className="flex flex-wrap gap-3">
        <label>竞品品牌<select className="glass-input ml-2 p-2" value={brand} onChange={event => { setBrand(event.target.value); setOffset(0) }}><option value="">请选择品牌</option>{brands.map(item => <option key={item.brand} value={item.brand}>{item.brand} · 图片 {item.image_count} / 视频 {item.video_count}</option>)}</select></label>
        <label>查看<select className="glass-input ml-2 p-2" value={kind} onChange={event => { setKind(event.target.value as 'image' | 'video'); setOffset(0) }}><option value="image">图片</option><option value="video">视频</option></select></label>
      </div>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      {!brand ? <p>选择品牌后查看参考素材；旧 SKU 竞品记录尚未自动迁移。</p> : loading ? <p>读取中…</p> : <>
        {!items.length && <p>当前品牌和素材形式下暂无记录。</p>}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{items.map(item => <article key={item.id} className="rounded-xl bg-white p-3">
          <div className="aspect-video overflow-hidden rounded-lg bg-stone-100">{item.asset_type === 'image' ? <SecureImage src={item.thumbnail_url || item.url} className="h-full w-full object-contain" /> : <SecureVideo src={item.url} controls className="h-full w-full object-contain" />}</div>
          <h3 className="mt-2 break-words font-bold">{item.original_file_name || '参考素材'}</h3>
          <p className="text-xs">维护人：{item.maintainer || '未填写'}</p>
          <p className="break-words text-xs">来源：{item.source_note || '未填写'}</p>
          <p className="text-xs">上传账号：{item.uploaded_by}</p>
          {item.notes && <p className="break-words text-xs">备注：{item.notes}</p>}
          {canUpload && <button className="mt-2 text-sm text-teal-700" onClick={() => { setEditing({ ...item }); setEditError('') }}>编辑参考字段</button>}
        </article>)}</div>
        <div className="flex gap-3"><button disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - 100))}>上一页</button><span>第 {offset / 100 + 1} 页</span><button disabled={items.length < 100} onClick={() => setOffset(value => value + 100)}>下一页</button></div>
      </>}
    </section>
    {editing && <div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-4">
      <section role="dialog" aria-modal="true" aria-label="编辑竞品参考字段" className="glass w-full max-w-xl space-y-3 p-5">
        <h2 className="font-bold">编辑竞品参考字段</h2>
        <p className="text-xs">修改品牌只调整分组，不替换文件，也不改变原上传账号。</p>
        <fieldset disabled={saving} className="space-y-3">
          <label className="block">竞品品牌<input className="glass-input mt-1 w-full p-2" maxLength={64} value={editing.brand} onChange={event => setEditing({ ...editing, brand: event.target.value })} /></label>
          <label className="block">素材维护人<input className="glass-input mt-1 w-full p-2" maxLength={100} value={editing.maintainer || ''} onChange={event => setEditing({ ...editing, maintainer: event.target.value || null })} /></label>
          <label className="block">来源说明<textarea className="glass-input mt-1 w-full p-2" maxLength={2000} value={editing.source_note || ''} onChange={event => setEditing({ ...editing, source_note: event.target.value || null })} /></label>
          <label className="block">备注<textarea className="glass-input mt-1 w-full p-2" maxLength={2000} value={editing.notes || ''} onChange={event => setEditing({ ...editing, notes: event.target.value || null })} /></label>
        </fieldset>
        {editError && <p role="alert" className="text-red-700">{editError}</p>}
        <div className="flex gap-3"><button disabled={saving} onClick={() => setEditing(null)}>取消</button><button disabled={saving} onClick={() => void saveMetadata()}>{saving ? '保存中…' : '保存'}</button></div>
      </section>
    </div>}
  </main>
}
