import { AppSessionProvider } from "@/components/AppSession"
import OfuqApp from "@/components/OfuqApp"
import { getPublicCatalog } from "@/lib/catalog"

export default async function OfuqPage({ path }: { path: string }) {
  const catalog = await getPublicCatalog()
  return (
    <AppSessionProvider><OfuqApp
      initialPath={path}
      initialCourses={catalog.courses}
      initialBooks={catalog.books}
    /></AppSessionProvider>
  )
}
