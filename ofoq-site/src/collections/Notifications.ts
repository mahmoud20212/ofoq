import type { CollectionConfig } from 'payload'
import { ownerOrStaff, staffOnly } from './access'

export const Notifications: CollectionConfig = {
  slug: 'notifications',
  admin: { group: 'الخدمات المشتركة', useAsTitle: 'title' },
  access: {
    create: staffOnly,
    delete: ownerOrStaff,
    read: ownerOrStaff,
    update: ownerOrStaff,
  },
  fields: [
    { name: 'owner', type: 'relationship', relationTo: 'users', required: true },
    { name: 'title', type: 'text', required: true },
    { name: 'message', type: 'textarea', required: true },
    { name: 'source', type: 'text', required: true },
    { name: 'href', type: 'text' },
    { name: 'read', type: 'checkbox', defaultValue: false },
  ],
}
