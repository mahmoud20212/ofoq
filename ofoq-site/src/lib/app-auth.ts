import 'server-only'
import { currentRecord } from '@/lib/keycloak'

// Public app identity is owned by Keycloak; Payload Admin remains independent.
export const appAuth = { async currentUser() { return (await currentRecord())?.user || null } }
