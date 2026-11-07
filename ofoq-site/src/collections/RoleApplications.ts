import type { CollectionConfig } from 'payload'
import { ownerOrStaff, staffField, staffOnly } from './access'

export const RoleApplications: CollectionConfig = {
  slug: 'role-applications',
  admin: { group: 'الحسابات', useAsTitle: 'requestedRole' },
  access: {
    create: ({ req }) => req.user?.collection === 'users',
    delete: staffOnly,
    read: ownerOrStaff,
    update: staffOnly,
  },
  fields: [
    { name: 'owner', type: 'relationship', relationTo: 'users', required: true },
    {
      name: 'requestedRole',
      type: 'select',
      required: true,
      options: [
        { label: 'معلم', value: 'teacher' },
        { label: 'مؤلف', value: 'author' },
      ],
    },
    { name: 'experience', type: 'textarea', required: true },
    {
      name: 'status',
      type: 'select',
      defaultValue: 'pending',
      options: ['pending', 'approved', 'rejected', 'changes-requested'],
      access: { create: staffField, update: staffField },
    },
    {
      name: 'decisionNote',
      type: 'textarea',
      access: { create: staffField, update: staffField },
    },
  ],
}
