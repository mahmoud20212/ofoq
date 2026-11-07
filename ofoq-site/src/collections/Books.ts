import type { Access, CollectionConfig } from 'payload'
import { creatorOnly, hasAppRole, isAdminCollection, staffOnly } from './access'

const readBooks: Access = ({ req }) => {
  if (isAdminCollection(req.user) || hasAppRole(req.user, ['author', 'moderator', 'admin']))
    return true
  return { status: { equals: 'published' } }
}

export const Books: CollectionConfig = {
  slug: 'books',
  admin: {
    group: 'وَرَق',
    useAsTitle: 'title',
    defaultColumns: ['title', 'authorName', 'status', 'price'],
  },
  access: {
    create: creatorOnly('author'),
    delete: staffOnly,
    read: readBooks,
    update: creatorOnly('author'),
  },
  fields: [
    { name: 'title', type: 'text', required: true },
    { name: 'slug', type: 'text', required: true, unique: true, index: true },
    { name: 'description', type: 'textarea', required: true },
    { name: 'category', type: 'text', required: true, index: true },
    { name: 'authorName', type: 'text', required: true },
    { name: 'author', type: 'relationship', relationTo: 'users' },
    { name: 'language', type: 'text', defaultValue: 'العربية' },
    { name: 'price', type: 'number', required: true, min: 0 },
    { name: 'rating', type: 'number', min: 0, max: 5, defaultValue: 0 },
    {
      name: 'formats',
      type: 'select',
      hasMany: true,
      required: true,
      options: ['pdf', 'epub'],
    },
    { name: 'allowDownload', type: 'checkbox', defaultValue: false },
    {
      name: 'rightsStatus',
      type: 'select',
      defaultValue: 'pending',
      options: ['pending', 'verified', 'disputed'],
    },
    {
      name: 'status',
      type: 'select',
      defaultValue: 'draft',
      options: [
        { label: 'مسودة', value: 'draft' },
        { label: 'قيد المراجعة', value: 'review' },
        { label: 'مطلوب تعديل', value: 'changes-requested' },
        { label: 'منشور', value: 'published' },
        { label: 'مرفوض', value: 'rejected' },
      ],
    },
  ],
}
