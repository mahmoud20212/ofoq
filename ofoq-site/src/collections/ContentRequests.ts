import type { CollectionConfig } from 'payload'
import { ownerOrStaff, staffField, staffOnly } from './access'

export const ContentRequests: CollectionConfig = {
  slug: 'content-requests',
  admin: { group: 'الخدمات المشتركة', useAsTitle: 'title' },
  access: {
    create: ({ req }) => req.user?.collection === 'users',
    delete: staffOnly,
    read: ownerOrStaff,
    update: ownerOrStaff,
  },
  fields: [
    { name: 'owner', type: 'relationship', relationTo: 'users', required: true },
    {
      name: 'type',
      type: 'select',
      required: true,
      options: [
        { label: 'دورة', value: 'course' },
        { label: 'كتاب', value: 'book' },
      ],
    },
    { name: 'title', type: 'text', required: true },
    { name: 'topic', type: 'text', required: true },
    { name: 'description', type: 'textarea', required: true },
    { name: 'supportCount', type: 'number', defaultValue: 1, min: 1 },
    {
      name: 'status',
      type: 'select',
      defaultValue: 'submitted',
      options: ['submitted', 'accepted', 'in-progress', 'available', 'rejected'],
      access: { create: staffField, update: staffField },
    },
  ],
}
