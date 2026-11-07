import type { Access, CollectionConfig } from 'payload'
import { creatorOnly, hasAppRole, isAdminCollection, staffOnly } from './access'

const readCourses: Access = ({ req }) => {
  if (isAdminCollection(req.user) || hasAppRole(req.user, ['teacher', 'moderator', 'admin']))
    return true
  return { status: { equals: 'published' } }
}

export const Courses: CollectionConfig = {
  slug: 'courses',
  admin: {
    group: 'مَسار',
    useAsTitle: 'title',
    defaultColumns: ['title', 'category', 'status', 'price'],
  },
  access: {
    create: creatorOnly('teacher'),
    delete: staffOnly,
    read: readCourses,
    update: creatorOnly('teacher'),
  },
  fields: [
    { name: 'title', type: 'text', required: true },
    { name: 'slug', type: 'text', required: true, unique: true, index: true },
    { name: 'description', type: 'textarea', required: true },
    { name: 'category', type: 'text', required: true, index: true },
    {
      name: 'level',
      type: 'select',
      required: true,
      options: ['beginner', 'intermediate', 'advanced'],
    },
    { name: 'language', type: 'text', defaultValue: 'العربية' },
    { name: 'instructorName', type: 'text', required: true },
    { name: 'instructor', type: 'relationship', relationTo: 'users' },
    { name: 'durationHours', type: 'number', required: true, min: 0 },
    { name: 'price', type: 'number', required: true, min: 0 },
    { name: 'rating', type: 'number', min: 0, max: 5, defaultValue: 0 },
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
    {
      name: 'outcomes',
      type: 'array',
      fields: [{ name: 'text', type: 'text', required: true }],
    },
    {
      name: 'curriculum',
      type: 'array',
      fields: [
        { name: 'title', type: 'text', required: true },
        {
          name: 'lessons',
          type: 'array',
          fields: [
            { name: 'title', type: 'text', required: true },
            { name: 'isPreview', type: 'checkbox', defaultValue: false },
            { name: 'durationMinutes', type: 'number', min: 0 },
          ],
        },
      ],
    },
  ],
}
