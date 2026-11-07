import type { Access, CollectionConfig } from 'payload'
import { isStaffUser } from './access'

const updateOwnPost: Access = ({ req }) => {
  if (isStaffUser(req.user)) return true
  if (req.user?.collection !== 'users') return false
  return { owner: { equals: req.user.id } }
}

export const CommunityPosts: CollectionConfig = {
  slug: 'community-posts',
  admin: { group: 'الخدمات المشتركة', useAsTitle: 'title' },
  access: {
    create: ({ req }) => req.user?.collection === 'users',
    delete: updateOwnPost,
    read: () => true,
    update: updateOwnPost,
  },
  fields: [
    { name: 'title', type: 'text', required: true },
    { name: 'slug', type: 'text', required: true, unique: true, index: true },
    { name: 'body', type: 'textarea', required: true },
    {
      name: 'type',
      type: 'select',
      required: true,
      options: ['question', 'idea', 'solution', 'discussion'],
    },
    { name: 'category', type: 'text', required: true },
    { name: 'owner', type: 'relationship', relationTo: 'users' },
    { name: 'authorName', type: 'text', required: true },
    { name: 'hidden', type: 'checkbox', defaultValue: false },
    {
      name: 'comments',
      type: 'array',
      fields: [
        { name: 'authorName', type: 'text', required: true },
        { name: 'body', type: 'textarea', required: true },
      ],
    },
  ],
}
