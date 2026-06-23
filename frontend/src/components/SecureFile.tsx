import { useEffect, useState } from 'react'
import { api } from '../services/api'

function shouldSignUrl(url: string | null | undefined) {
  if (!url) return false
  return url.startsWith('/uploads/') || url.includes('/uploads/')
}

export function useSignedFileUrl(url: string | null | undefined) {
  const [resolvedUrl, setResolvedUrl] = useState(() => {
    if (!url || shouldSignUrl(url)) return ''
    return url
  })
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function resolve() {
      if (!url) {
        setResolvedUrl('')
        return
      }
      if (!shouldSignUrl(url)) {
        setResolvedUrl(url)
        return
      }
      setResolvedUrl('')
      setLoading(true)
      try {
        const signed = await api.files.sign(url)
        if (!cancelled) setResolvedUrl(signed.url)
      } catch {
        if (!cancelled) setResolvedUrl('')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    resolve()
    return () => {
      cancelled = true
    }
  }, [url])

  return { url: resolvedUrl, loading }
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
  if (!signed.url) {
    return <div className={className} />
  }
  return (
    <img
      src={signed.url}
      alt={alt || ''}
      className={className}
      onClick={onClick ? () => onClick(signed.url) : undefined}
      draggable={draggable}
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
  if (!signed.url) {
    return <div className={className} />
  }
  return <video src={signed.url} controls={controls} className={className} />
}
