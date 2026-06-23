import { useState, useCallback, useRef } from 'react'
import { SecureImage, useSignedFileUrl } from '../SecureFile'

interface ImagePreviewProps {
  imageUrl: string | null
  onClear: () => void
}

export default function ImageUploader({ onImageSelect }: { onImageSelect: (file: File | null) => void }) {
  const [preview, setPreview] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFile = useCallback((file: File) => {
    if (!file.type.startsWith('image/')) return
    const url = URL.createObjectURL(file)
    setPreview(url)
    onImageSelect(file)
  }, [onImageSelect])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }, [handleFile])

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => setIsDragging(false)

  const handleClick = () => fileInputRef.current?.click()

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) handleFile(file)
  }

  const handleClear = () => {
    setPreview(null)
    onImageSelect(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  return (
    <div className="h-full flex flex-col items-center justify-center">
      {preview ? (
        <div className="relative w-full h-full flex items-center justify-center group">
          <img
            src={preview}
            alt="Preview"
            className="max-w-full max-h-full object-contain rounded-xl"
          />
          <button
            onClick={handleClear}
            className="absolute top-2 right-2 w-8 h-8 rounded-full bg-black/50 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
          >
            ×
          </button>
        </div>
      ) : (
        <div
          onClick={handleClick}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          className={`w-full h-full min-h-[300px] flex flex-col items-center justify-center border-2 border-dashed rounded-2xl cursor-pointer transition-all duration-300 ${
            isDragging
              ? 'border-apple-blue bg-blue-50/50'
              : 'border-black/10 hover:border-black/20 hover:bg-black/[0.02]'
          }`}
        >
          <svg className="w-12 h-12 text-apple-gray-medium mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <p className="text-sm text-apple-gray-medium font-medium">
            {isDragging ? '松开以放置图片' : '拖拽图片到此处或点击上传'}
          </p>
          <p className="text-xs text-apple-gray-medium/60 mt-1">支持 JPG、PNG、WebP 格式</p>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={handleInputChange}
            className="hidden"
          />
        </div>
      )}
    </div>
  )
}

export function ImagePreview({ imageUrl, onClear }: ImagePreviewProps) {
  const signed = useSignedFileUrl(imageUrl)

  if (!imageUrl) {
    return (
      <div className="w-full h-full min-h-[300px] flex flex-col items-center justify-center text-apple-gray-medium">
        <svg className="w-16 h-16 mb-4 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={0.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.41a2.25 2.25 0 013.182 0l2.909 2.91m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
        </svg>
        <p className="text-sm">生成结果将在此处显示</p>
      </div>
    )
  }

  return (
    <div className="relative w-full h-full flex items-center justify-center group animate-fade-in">
      <SecureImage
        src={imageUrl}
        alt="Generated"
        className="max-w-full max-h-full object-contain rounded-xl"
      />
      <div className="absolute top-3 right-3 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <a
          href={signed.url || imageUrl}
          download
          className="w-9 h-9 rounded-full glass-light flex items-center justify-center text-apple-text hover:text-apple-blue transition-colors"
          title="下载"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
        </a>
        <button
          onClick={onClear}
          className="w-9 h-9 rounded-full glass-light flex items-center justify-center text-apple-text hover:text-red-500 transition-colors"
          title="清除"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  )
}
