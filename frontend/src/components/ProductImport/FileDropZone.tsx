import { useState, useRef, useCallback } from 'react'

interface FileDropZoneProps {
  accept: string
  multiple: boolean
  label: string
  onFiles: (files: File[]) => void
}

export default function FileDropZone({ accept, multiple, label, onFiles }: FileDropZoneProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [fileNames, setFileNames] = useState<string[]>([])
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return
      const arr = Array.from(files)
      setFileNames(arr.map((f) => f.name))
      onFiles(arr)
    },
    [onFiles],
  )

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      handleFiles(e.dataTransfer.files)
    },
    [handleFiles],
  )

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => setIsDragging(false)

  const handleClick = () => inputRef.current?.click()

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    handleFiles(e.target.files)
  }

  const handleClear = () => {
    setFileNames([])
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div className="w-full">
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={handleClick}
        className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors ${
          isDragging
            ? 'border-blue-400 bg-blue-500/10'
            : 'border-white/20 hover:border-blue-400/60 bg-white/5'
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          onChange={handleInputChange}
          className="hidden"
        />
        <svg
          className="mx-auto h-10 w-10 text-white/40 mb-2"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
          />
        </svg>
        <p className="text-sm text-white/60">{label}</p>
        <p className="text-xs text-white/30 mt-1">
          {multiple ? '支持多文件上传' : '点击或拖拽文件到此处'}
        </p>
      </div>

      {fileNames.length > 0 && (
        <div className="mt-3 space-y-1">
          {fileNames.map((name, i) => (
            <div
              key={i}
              className="flex items-center justify-between bg-white/5 rounded-lg px-3 py-2 text-sm text-white/70"
            >
              <span className="truncate flex-1">{name}</span>
              <span className="text-white/30 text-xs ml-2">
                {(name.endsWith('.xlsx') || name.endsWith('.xls')) ? 'Excel' : name.split('.').pop()?.toUpperCase()}
              </span>
            </div>
          ))}
          <button
            onClick={(e) => {
              e.stopPropagation()
              handleClear()
            }}
            className="text-xs text-red-400 hover:text-red-300 mt-1"
          >
            清除已选文件
          </button>
        </div>
      )}
    </div>
  )
}
