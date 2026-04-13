/**
 * VerifyEmailPage - 6-digit code entry for email verification
 */

import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { useAuth } from '../../hooks/useAuth';
import { resendVerificationCode } from '../../services/auth';

export const VerifyEmailPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { verifyEmail, isLoading } = useAuth();
  const [code, setCode] = useState('');
  const [isResending, setIsResending] = useState(false);
  const userId = searchParams.get('user_id');
  const email = sessionStorage.getItem('pendingVerificationEmail');

  useEffect(() => {
    if (!userId) navigate('/login');
  }, [userId, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId) return;
    try {
      await verifyEmail(userId, code);
      sessionStorage.removeItem('pendingVerificationEmail');
      navigate('/');
    } catch (error) {
      // Error handled by useAuth
    }
  };

  const handleResend = async () => {
    if (!email) {
      toast.error('Email not found. Please register again.');
      navigate('/register');
      return;
    }
    setIsResending(true);
    try {
      const response = await resendVerificationCode(email);
      toast.success(response.message || 'Verification code sent!');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to resend code');
    } finally {
      setIsResending(false);
    }
  };

  const handleCodeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setCode(e.target.value.replace(/\D/g, '').slice(0, 6));
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{ backgroundColor: 'var(--bg-base)' }}
    >
      <div className="w-full max-w-sm">

        <div className="mb-8 text-center">
          <span style={{ fontWeight: 600, fontSize: '18px', color: 'var(--text-primary)', letterSpacing: '-0.01em' }}>
            AI Subs
          </span>
        </div>

        <div
          className="rounded-lg p-6"
          style={{ backgroundColor: 'var(--bg-subtle)', border: '1px solid var(--border-subtle)' }}
        >
          <h1 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
            Verify your email
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '20px' }}>
            Enter the 6-digit code we sent to your email
          </p>

          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label
                htmlFor="code"
                style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '6px' }}
              >
                Verification code
              </label>
              <input
                id="code"
                type="text"
                inputMode="numeric"
                value={code}
                onChange={handleCodeChange}
                className="input-base w-full text-center tracking-widest"
                style={{ fontSize: '22px', letterSpacing: '0.25em', fontVariantNumeric: 'tabular-nums' }}
                placeholder="000000"
                required
                autoFocus
                disabled={isLoading}
                maxLength={6}
              />
            </div>

            <button
              type="submit"
              disabled={isLoading || code.length !== 6}
              className="btn-primary w-full"
              style={{ marginTop: '8px', justifyContent: 'center' }}
            >
              {isLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Verifying…
                </span>
              ) : (
                'Verify email'
              )}
            </button>
          </form>
        </div>

        <p style={{ textAlign: 'center', marginTop: '16px', fontSize: '13px', color: 'var(--text-tertiary)' }}>
          Didn't receive the code?{' '}
          <button
            type="button"
            onClick={handleResend}
            disabled={isResending || !email}
            style={{
              color: 'var(--accent)',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontWeight: 500,
              fontSize: '13px',
              opacity: (isResending || !email) ? 0.5 : 1,
            }}
          >
            {isResending ? 'Sending…' : 'Resend'}
          </button>
        </p>
      </div>
    </div>
  );
};
