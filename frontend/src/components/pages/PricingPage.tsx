import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import axios from "axios";
import toast from "react-hot-toast";
import { API_BASE_URL } from "../../config";
import { useAuth } from "../../hooks/useAuth";

interface Tier {
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

const Check = () => (
  <svg className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: 'var(--accent)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
  </svg>
);

const Dash = () => (
  <svg className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: 'var(--text-tertiary)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14" />
  </svg>
);

export const PricingPage = () => {
  const [tiers, setTiers] = useState<Tier[]>([]);
  const [loading, setLoading] = useState(true);
  const { user } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await axios.get(`${API_BASE_URL}/api/billing/plans`);
        if (!cancelled) setTiers(res.data.tiers || []);
      } catch (e) {
        console.warn("Failed to load pricing", e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const [checkoutLoading, setCheckoutLoading] = useState(false);

  const handleCta = async (tier: Tier) => {
    if (tier.id === "free") {
      navigate(user ? "/" : "/register");
      return;
    }
    if (!user) {
      navigate("/register?next=/pricing");
      return;
    }
    setCheckoutLoading(true);
    try {
      const res = await axios.post(
        `${API_BASE_URL}/api/billing/checkout`,
        {},
        { withCredentials: true }
      );
      if (res.data?.url) {
        window.location.href = res.data.url;  // Stripe-hosted checkout
      } else {
        toast.error("Couldn't start checkout. Please try again.");
      }
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      if (typeof detail === "string" && detail.includes("not configured")) {
        toast.error("Billing isn't configured yet. Try again shortly.");
      } else {
        toast.error("Checkout failed. Please try again.");
      }
      console.error("Checkout failed", e);
    } finally {
      setCheckoutLoading(false);
    }
  };

  return (
    <div
      className="min-h-screen"
      style={{ background: 'var(--bg-base)', color: 'var(--text-primary)' }}
    >
      {/* Header */}
      <header
        className="sticky top-0 z-10 px-6 py-4 border-b backdrop-blur-sm"
        style={{
          background: 'oklch(from var(--bg-base) l c h / 0.85)',
          borderColor: 'var(--border-subtle)',
        }}
      >
        <div className="max-w-5xl mx-auto flex items-center justify-between">
          <Link
            to="/"
            className="text-sm font-semibold tracking-tight"
            style={{ color: 'var(--text-primary)' }}
          >
            AI-Subs
          </Link>
          <nav className="flex items-center gap-3">
            {user ? (
              <Link to="/" className="btn-ghost text-xs">Back to app</Link>
            ) : (
              <>
                <Link to="/login" className="btn-ghost text-xs">Sign in</Link>
                <Link to="/register" className="btn-primary text-xs">Get started</Link>
              </>
            )}
          </nav>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-16">
        {/* Hero */}
        <div className="text-center mb-14">
          <h1
            className="text-3xl sm:text-4xl font-semibold tracking-tight mb-3"
            style={{ color: 'var(--text-primary)' }}
          >
            Simple pricing. Powerful video intelligence.
          </h1>
          <p
            className="text-base max-w-xl mx-auto leading-relaxed"
            style={{ color: 'var(--text-secondary)' }}
          >
            Transcribe, search, and chat with your videos. Start free,
            upgrade when you need more.
          </p>
        </div>

        {/* Tiers */}
        {loading ? (
          <div className="flex justify-center py-16">
            <span className="spinner spinner-lg" />
          </div>
        ) : (
          <div className="grid gap-6 sm:grid-cols-2 max-w-3xl mx-auto">
            {tiers.map((tier) => (
              <div
                key={tier.id}
                className="relative rounded-xl p-6 flex flex-col"
                style={{
                  background: 'var(--bg-surface)',
                  border: tier.highlighted
                    ? '1px solid var(--accent-border)'
                    : '1px solid var(--border-subtle)',
                  boxShadow: tier.highlighted ? 'var(--shadow-overlay)' : undefined,
                }}
              >
                {tier.highlighted && (
                  <div
                    className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 rounded-full text-[10px] font-semibold uppercase tracking-wider"
                    style={{ background: 'var(--accent)', color: 'var(--accent-text)' }}
                  >
                    Recommended
                  </div>
                )}

                <div className="mb-4">
                  <h2
                    className="text-lg font-semibold"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {tier.name}
                  </h2>
                  <p
                    className="text-xs mt-0.5"
                    style={{ color: 'var(--text-tertiary)' }}
                  >
                    {tier.tagline}
                  </p>
                </div>

                <div className="mb-6">
                  <div className="flex items-baseline gap-1">
                    <span
                      className="text-4xl font-bold tabular-nums"
                      style={{ color: 'var(--text-primary)' }}
                    >
                      €{tier.price_eur_monthly}
                    </span>
                    <span className="text-sm" style={{ color: 'var(--text-tertiary)' }}>
                      /month
                    </span>
                  </div>
                  {tier.price_eur_yearly && (
                    <p className="text-xs mt-1" style={{ color: 'var(--text-tertiary)' }}>
                      or €{tier.price_eur_yearly}/year (save €
                      {tier.price_eur_monthly * 12 - tier.price_eur_yearly})
                    </p>
                  )}
                </div>

                <ul className="space-y-2 mb-6 flex-1">
                  {tier.features.map((f) => (
                    <li
                      key={f}
                      className="flex items-start gap-2 text-sm"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      <Check />
                      <span>{f}</span>
                    </li>
                  ))}
                  {tier.missing.map((m) => (
                    <li
                      key={m}
                      className="flex items-start gap-2 text-sm"
                      style={{ color: 'var(--text-tertiary)' }}
                    >
                      <Dash />
                      <span className="line-through opacity-70">{m}</span>
                    </li>
                  ))}
                </ul>

                <button
                  onClick={() => handleCta(tier)}
                  disabled={checkoutLoading && tier.id !== 'free'}
                  className={tier.highlighted ? 'btn-primary w-full' : 'btn-secondary w-full'}
                >
                  {checkoutLoading && tier.id !== 'free' ? (
                    <>
                      <span className="spinner mr-2" style={{ width: '0.875rem', height: '0.875rem', borderWidth: '1.5px' }} />
                      Redirecting…
                    </>
                  ) : tier.cta}
                </button>
              </div>
            ))}
          </div>
        )}

        {/* FAQ-ish footer */}
        <div
          className="mt-16 max-w-2xl mx-auto text-center text-xs space-y-2"
          style={{ color: 'var(--text-tertiary)' }}
        >
          <p>Cancel anytime · No credit card required for Free · EU VAT handled automatically</p>
          <p>
            Questions? Email <a href="mailto:hello@ai-subs.app" style={{ color: 'var(--accent)' }}>hello@ai-subs.app</a>
          </p>
        </div>
      </main>
    </div>
  );
};

export default PricingPage;
