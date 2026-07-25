/**
 * Supabase client configuration
 * Provides real-time database connection for background job tracking
 *
 * In local mode (VITE_LOCAL_MODE=true) or when credentials are missing the
 * client is null — job tracking falls back to polling (see useJobTracker).
 */

import { createClient, SupabaseClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const IS_LOCAL_MODE = import.meta.env.VITE_LOCAL_MODE === 'true';

let client: SupabaseClient | null = null;
if (!IS_LOCAL_MODE && supabaseUrl && supabaseAnonKey) {
  client = createClient(supabaseUrl, supabaseAnonKey);
} else if (!IS_LOCAL_MODE) {
  console.warn('Supabase credentials not configured. Real-time features will be unavailable.');
}

export const supabase = client;
