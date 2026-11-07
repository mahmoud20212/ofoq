import 'server-only'

import { getPayloadClient } from '@/lib/payload'

export type PublicCourse = {
  id: string
  title: string
  category: string
  teacher: string
  duration: string
  rating: string
  progress: number
  tone: string
}

export type PublicBook = {
  id: string
  title: string
  author: string
  category: string
  color: string
}

export async function getPublicCatalog() {
  const payload = await getPayloadClient()
  const [courseResult, bookResult] = await Promise.all([
    payload.find({
      collection: 'courses',
      where: { status: { equals: 'published' } },
      sort: '-createdAt',
      limit: 50,
      overrideAccess: false,
    }),
    payload.find({
      collection: 'books',
      where: { status: { equals: 'published' } },
      sort: '-createdAt',
      limit: 50,
      overrideAccess: false,
    }),
  ])

  const courses: PublicCourse[] = courseResult.docs.map((course, index) => ({
    id: course.slug,
    title: course.title,
    category: course.category,
    teacher: course.instructorName,
    duration: `${course.durationHours} ساعات`,
    rating: String(course.rating || 'جديد'),
    progress: 0,
    tone: ['blue', 'purple', 'sky'][index % 3],
  }))

  const books: PublicBook[] = bookResult.docs.map((book, index) => ({
    id: book.slug,
    title: book.title,
    author: book.authorName,
    category: book.category,
    color: ['violet', 'blue', 'lavender', 'deep'][index % 4],
  }))

  return { courses, books }
}
