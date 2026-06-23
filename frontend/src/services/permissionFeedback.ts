import type { User } from '../types'

export const NO_PERMISSION_MESSAGE = '您所在的团队暂无该操作权限，如需使用请联系管理员'
export const NO_PERMISSION_EVENT = 'caiyan:permission-denied'

export function showNoPermissionToast() {
  window.dispatchEvent(new CustomEvent(NO_PERMISSION_EVENT))
}

export function canUsePermission(
  user: User | null,
  isManagement: boolean,
  permissionKey: string,
) {
  return isManagement || !!user?.permissions?.includes(permissionKey)
}
