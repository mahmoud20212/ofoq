import type { CollectionConfig } from 'payload'
import { ownProfileOrStaff, staffField, staffOnly } from './access'

export const Users: CollectionConfig = {
  slug: 'users',
  auth: true,
  admin: {
    hidden: true,
    useAsTitle: 'name',
  },
  access: {
    create: () => true,
    delete: staffOnly,
    read: ownProfileOrStaff,
    update: ownProfileOrStaff,
  },
  fields: [
    {
      name: 'name',
      type: 'text',
      required: true,
    },
    {
      name: 'roles',
      type: 'select',
      hasMany: true,
      defaultValue: ['student'],
      options: [
        { label: 'طالب', value: 'student' },
        { label: 'معلم', value: 'teacher' },
        { label: 'مؤلف', value: 'author' },
        { label: 'مشرف', value: 'moderator' },
        { label: 'مدير', value: 'admin' },
      ],
      access: {
        create: staffField,
        update: staffField,
      },
    },
    {
      name: 'accountStatus',
      type: 'select',
      defaultValue: 'active',
      options: [
        { label: 'نشط', value: 'active' },
        { label: 'موقوف', value: 'suspended' },
      ],
      access: {
        create: staffField,
        update: staffField,
      },
    },
    {
      name: 'bio',
      type: 'textarea',
    },
    {
      name: 'preferredTheme',
      type: 'select',
      defaultValue: 'dark',
      options: [
        { label: 'داكن', value: 'dark' },
        { label: 'فاتح', value: 'light' },
        { label: 'حسب النظام', value: 'system' },
      ],
    },
  ],
}
