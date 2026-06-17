/**
 * lib/supabase.ts — Supabase browser client.
 *
 * This is the TypeScript equivalent of bot/db/supabase_client.py — but for the
 * browser. Key difference: we use the ANON key here (safe for public exposure
 * because Row Level Security only allows SELECT). The Python bot uses the
 * SERVICE key which bypasses RLS for writes.
 *
 * createClient() returns a typed client — Supabase infers query shapes from
 * the schema when you use codegen, but for v1 we keep it simple with manual types.
 */

import { createClient } from '@supabase/supabase-js'

// Vite exposes env vars prefixed with VITE_ via import.meta.env.
// This is the Vite equivalent of process.env in Node/Next.js.
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error(
    'Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY — check your .env.local'
  )
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
