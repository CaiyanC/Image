import { useEffect, useState } from 'react'
import { api } from '../services/api'
import { useAuthStore } from '../store/authStore'

type SignedCacheEntry = { url: string; expiresAt: number }
type DeferredSignedUrl = {
  promise: Promise<string>
  resolve: (url: string) => void
  reject: (error: unknown) => void
}

const signedUrlCache = new Map<string, SignedCacheEntry>()
const pendingSignedUrls = new Map<string, DeferredSignedUrl>()
const queuedSignedPaths = new Set<string>()
let batchScheduled = false
let cacheRevision = 0

// File capabilities belong to the account that requested them.
useAuthStore.subscribe((state, previous) => {
  if (state.user === previous.user) return
  cacheRevision += 1
  signedUrlCache.clear()
  pendingSignedUrls.forEach((pending) => pending.reject(new Error('登录状态已变化，请重试')))
  pendingSignedUrls.clear()
  queuedSignedPaths.clear()
})

function signingPathKey(url: string) {
  const uploadIndex = url.indexOf('/uploads/')
  return uploadIndex >= 0 ? url.slice(uploadIndex) : url
}

function requestSignedUrl(path: string): Promise<string> {
  path = signingPathKey(path)
  const cached = signedUrlCache.get(path)
  if (cached && cached.expiresAt > Date.now() + 30_000) return Promise.resolve(cached.url)
  const pending = pendingSignedUrls.get(path)
  if (pending) return pending.promise

  let resolve!: (url: string) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<string>((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  pendingSignedUrls.set(path, { promise, resolve, reject })
  queuedSignedPaths.add(path)
  if (!batchScheduled) {
    batchScheduled = true
    window.setTimeout(flushSignedUrlBatch, 0)
  }
  return promise
}

async function flushSignedUrlBatch() {
  const revision = cacheRevision
  batchScheduled = false
  const paths = Array.from(queuedSignedPaths).slice(0, 100)
  paths.forEach((path) => queuedSignedPaths.delete(path))
  if (queuedSignedPaths.size > 0) {
    batchScheduled = true
    window.setTimeout(flushSignedUrlBatch, 0)
  }
  if (paths.length === 0) return
  try {
    const items = await api.files.signBatch(paths)
    if (revision !== cacheRevision) return
    const byPath = new Map(items.map((item) => [item.path, item]))
    for (const path of paths) {
      const pending = pendingSignedUrls.get(path)
      const item = byPath.get(path)
      if (!pending) continue
      if (!item) {
        pending.reject(new Error(`Missing signed URL for ${path}`))
        continue
      }
      signedUrlCache.set(path, {
        url: item.url,
        expiresAt: Date.now() + Math.max(0, item.expires_in - 30) * 1000,
      })
      pending.resolve(item.url)
    }
  } catch (error) {
    if (revision === cacheRevision) paths.forEach((path) => pendingSignedUrls.get(path)?.reject(error))
  } finally {
    if (revision === cacheRevision) paths.forEach((path) => pendingSignedUrls.delete(path))
  }
}

function shouldSignUrl(url: string | null | undefined) {
  if (!url) return false
  return url.startsWith('/uploads/') || url.includes('/uploads/')
}

export function useSignedFileUrl(url: string | null | undefined) {
  const user = useAuthStore((state) => state.user)
  const [resolvedUrl, setResolvedUrl] = useState(() => {
    if (!url || shouldSignUrl(url)) return ''
    return url
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const [retryKey, setRetryKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    async function resolve() {
      if (!url) {
        setResolvedUrl('')
        setError(false)
        return
      }
      if (!shouldSignUrl(url)) {
        setResolvedUrl(url)
        setError(false)
        return
      }
      setResolvedUrl('')
      setError(false)
      setLoading(true)
      try {
        const signedUrl = await requestSignedUrl(url)
        if (!cancelled) setResolvedUrl(signedUrl)
      } catch {
        if (!cancelled) {
          setResolvedUrl('')
          setError(true)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    resolve()
    return () => {
      cancelled = true
    }
  }, [url, retryKey, user])

  return {
    url: resolvedUrl,
    loading,
    error,
    retry: () => {
      if (url) signedUrlCache.delete(signingPathKey(url))
      setRetryKey((value) => value + 1)
    },
  }
}

export function useFileDownload(url: string | null | undefined) {
  const user = useAuthStore((state) => state.user)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState('')
  // SecureImage callbacks may pass an already resolved preview URL.
  const path = Array.from(signedUrlCache).find(([, entry]) => entry.url === url)?.[0]
    || signingPathKey(url || '')
  const productMedia = /^\/uploads\/(images|videos|assets)\//.test(path)
  const ownerMedia = /^\/uploads\/(generated|reference-images)\//.test(path)
  const canPreviewMedia = ['media.read', 'media.search', 'product.read', 'product.full.view', 'product.edit']
    .some((permission) => user?.permissions?.includes(permission))
  const canDownload = !!user && (ownerMedia || (productMedia
    && canPreviewMedia && !!user.permissions?.includes('media.download')))

  useEffect(() => setDownloadError(''), [url, user])

  const download = async () => {
    if (!canDownload || downloading) return
    setDownloading(true)
    setDownloadError('')
    try {
      // Never reuse a preview capability or fall back to the raw upload URL.
      const signed = await api.files.sign(path, 'download')
      if (useAuthStore.getState().user !== user) return
      const anchor = document.createElement('a')
      anchor.href = signed.url
      anchor.download = ''
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : '下载失败，请重试')
    } finally {
      setDownloading(false)
    }
  }

  return { canDownload, download, downloading, downloadError }
}

export function SecureImage({
  src,
  alt,
  className,
  onClick,
  draggable,
}: {
  src: string
  alt?: string
  className?: string
  onClick?: (resolvedUrl: string) => void
  draggable?: boolean
}) {
  const signed = useSignedFileUrl(src)
  const [loadError, setLoadError] = useState(false)
  useEffect(() => setLoadError(false), [signed.url])
  if (signed.loading) {
    return <div className={className}>图片加载中…</div>
  }
  if (!signed.url || signed.error || loadError) {
    return (
      <div
        className={className}
        role="img"
        aria-label={alt || '图片加载失败'}
        title="图片加载失败，点击重试"
        onClick={signed.retry}
      >
        <span>图片加载失败</span>
      </div>
    )
  }
  return (
    <img
      src={signed.url}
      alt={alt || ''}
      className={className}
      onClick={onClick ? () => onClick(signed.url) : undefined}
      draggable={draggable}
      onError={() => setLoadError(true)}
    />
  )
}

export function SecureVideo({
  src,
  controls,
  className,
}: {
  src: string
  controls?: boolean
  className?: string
}) {
  const signed = useSignedFileUrl(src)
  const { canDownload, download, downloading, downloadError } = useFileDownload(src)
  const [loadError, setLoadError] = useState(false)
  useEffect(() => setLoadError(false), [signed.url])
  if (signed.loading) {
    return <div className={className}>视频加载中…</div>
  }
  if (!signed.url || signed.error || loadError) {
    return <div className={className} onClick={signed.retry}>视频加载失败，点击重试</div>
  }
  return <>
    <video src={signed.url} controls={controls} controlsList="nodownload" className={className} onError={() => setLoadError(true)} />
    {controls && canDownload && <button type="button" disabled={downloading} onClick={(event) => {
      event.stopPropagation()
      void download()
    }}>{downloading ? '下载中…' : '下载原视频'}</button>}
    {downloadError && <span role="alert">{downloadError}</span>}
  </>
}
