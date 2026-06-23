import { useEffect, useRef, useState } from 'react'
import { NO_PERMISSION_EVENT, NO_PERMISSION_MESSAGE } from '../services/permissionFeedback'

export default function PermissionToast() {
  const [visible, setVisible] = useState(false)
  const timerRef = useRef<number | null>(null)

  useEffect(() => {
    const show = () => {
      setVisible(true)
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
      timerRef.current = window.setTimeout(() => setVisible(false), 3500)
    }
    window.addEventListener(NO_PERMISSION_EVENT, show)
    return () => {
      window.removeEventListener(NO_PERMISSION_EVENT, show)
      if (timerRef.current !== null) window.clearTimeout(timerRef.current)
    }
  }, [])

  if (!visible) return null

  return (
    <div
      role="alert"
      className="fixed right-5 top-5 z-[100] max-w-sm rounded-lg border border-amber-200 bg-white px-4 py-3 text-sm font-medium text-apple-text shadow-xl"
    >
      {NO_PERMISSION_MESSAGE}
    </div>
  )
}
