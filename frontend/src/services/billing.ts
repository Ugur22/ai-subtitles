import { api } from './api';

export interface Tier {
  id: string;
  name: string;
  price_eur_monthly: number;
  price_eur_yearly?: number;
  tagline: string;
  features: string[];
  missing: string[];
  cta: string;
  highlighted?: boolean;
}

export const getPlans = async (): Promise<Tier[]> => {
  const response = await api.get<{ tiers?: Tier[] }>('/api/billing/plans');
  return response.data.tiers || [];
};

/** Returns the Stripe-hosted checkout URL, when the backend provides one. */
export const startCheckout = async (): Promise<string | undefined> => {
  const response = await api.post<{ url?: string }>('/api/billing/checkout', {});
  return response.data?.url;
};
