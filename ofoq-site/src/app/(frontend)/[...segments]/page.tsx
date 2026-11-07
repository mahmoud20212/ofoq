import OfuqPage from '@/components/OfuqPage'
import { redirect } from 'next/navigation'

export function generateStaticParams() {
  return ['privacy', 'terms'].map((path) => ({ segments: [path] }))
}

export default async function RoutedPage({ params }: { params: Promise<{ segments: string[] }> }) {
  const { segments } = await params
  const path = `/${segments.join('/')}`
  if (path.includes('/dashboard') || path.startsWith('/account') || path === '/myPage') redirect('/auth/my-page')
  if (path !== '/privacy' && path !== '/terms') redirect('/')
  return <OfuqPage path={path} />
}
