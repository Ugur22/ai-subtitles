/**
 * Supabase client configuration
 * Provides real-time database connection for background job tracking
 */

import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  console.warn('Supabase credentials not configured. Real-time features will be unavailable.');
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
