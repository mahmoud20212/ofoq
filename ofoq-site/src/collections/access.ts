import type { Access, FieldAccess } from 'payload'

type AppRole = 'student' | 'teacher' | 'author' | 'moderator' | 'admin'

export const isAdminCollection = (user: unknown): boolean =>
  Boolean(user && typeof user === 'object' && 'collection' in user && user.collection === 'admins')

export const hasAppRole = (user: unknown, roles: AppRole[]): boolean => {
  if (isAdminCollection(user)) return true
  if (!user || typeof user !== 'object' || !('collection' in user)) return false
  if (user.collection !== 'users' || !('roles' in user)) return false
  const userRoles = Array.isArray(user.roles) ? user.roles : []
  return roles.some((role) => userRoles.includes(role))
}

export const isStaffUser = (user: unknown): boolean =>
  isAdminCollection(user) || hasAppRole(user, ['moderator', 'admin'])

export const staffOnly: Access = ({ req }) => isStaffUser(req.user)

export const creatorOnly =
  (role: 'teacher' | 'author'): Access =>
  ({ req }) =>
    hasAppRole(req.user, [role, 'admin'])

export const ownerOrStaff: Access = ({ req }) => {
  if (isStaffUser(req.user)) return true
  if (req.user?.collection !== 'users') return false
  return { owner: { equals: req.user.id } }
}

export const ownProfileOrStaff: Access = ({ req }) => {
  if (isStaffUser(req.user)) return true
  if (req.user?.collection !== 'users') return false
  return { id: { equals: req.user.id } }
}

export const staffField: FieldAccess = ({ req }) =>
  isAdminCollection(req.user) || hasAppRole(req.user, ['moderator', 'admin'])
