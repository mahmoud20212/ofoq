'use server'
import { redirect } from 'next/navigation'
export async function loginAction() { redirect('/auth/login') }
export async function registerAction() { redirect('/auth/register') }
