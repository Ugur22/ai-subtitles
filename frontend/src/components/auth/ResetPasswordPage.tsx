/**
 * ResetPasswordPage - Enter code and new password
 */

import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { resetPassword } from '../../services/auth';

export const ResetPasswordPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [localError, setLocalError] = useState('');
  const email = searchParams.get('email') || '';

  useEffect(() => {
    if (!email) navigate('/forgot-password');
  }, [email, navigate]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError('');
    if (newPassword !== confirmPassword) { setLocalError('Passwords do not match'); return; }
    if (newPassword.length < 8) { setLocalError('Password must be at least 8 characters'); return; }

    setIsLoading(true);
    try {
      await resetPassword(email, code, newPassword);
      toast.success('Password reset successfully!');
      navigate('/login');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Reset failed');
    } finally {
      setIsLoading(false);
    }
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
            Reset password
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '20px' }}>
            Enter the code from your email and your new password
          </p>

          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label htmlFor="code" style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '6px' }}>
                Reset code
              </label>
              <input
                id="code"
                type="text"
                inputMode="numeric"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                className="input-base w-full text-center tracking-widest"
                style={{ fontSize: '20px', letterSpacing: '0.2em', fontVariantNumeric: 'tabular-nums' }}
                placeholder="000000"
                required
                autoFocus
                disabled={isLoading}
                maxLength={6}
              />
            </div>

            <div>
              <label htmlFor="newPassword" style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '6px' }}>
                New password
              </label>
              <input id="newPassword" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
                className="input-base w-full" placeholder="At least 8 characters" required disabled={isLoading} />
            </div>

            <div>
              <label htmlFor="confirmPassword" style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '6px' }}>
                Confirm password
              </label>
              <input id="confirmPassword" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)}
                className="input-base w-full" placeholder="Repeat password" required disabled={isLoading} />
            </div>

            {localError && (
              <div className="rounded-md px-3 py-2" style={{ backgroundColor: 'oklch(65% 0.20 25 / 0.1)', border: '1px solid oklch(65% 0.20 25 / 0.3)' }}>
                <p style={{ fontSize: '13px', color: 'var(--c-error)' }}>{localError}</p>
              </div>
            )}

            <button type="submit" disabled={isLoading || code.length !== 6} className="btn-primary w-full" style={{ marginTop: '8px', justifyContent: 'center' }}>
              {isLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Resetting…
                </span>
              ) : 'Reset password'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};
