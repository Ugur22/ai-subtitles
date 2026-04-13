/**
 * RegisterPage - Registration form with invite code
 */

import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';

export const RegisterPage: React.FC = () => {
  const navigate = useNavigate();
  const { register, isLoading } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [localError, setLocalError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLocalError('');

    if (password !== confirmPassword) {
      setLocalError('Passwords do not match');
      return;
    }
    if (password.length < 8) {
      setLocalError('Password must be at least 8 characters');
      return;
    }

    try {
      const userId = await register(email, password, inviteCode);
      sessionStorage.setItem('pendingVerificationEmail', email);
      navigate(`/verify-email?user_id=${userId}`);
    } catch (error) {
      // Error handled by useAuth (toast shown)
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
          style={{
            backgroundColor: 'var(--bg-subtle)',
            border: '1px solid var(--border-subtle)',
          }}
        >
          <h1 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '4px' }}>
            Create account
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '20px' }}>
            You'll need an invite code to register
          </p>

          <form onSubmit={handleSubmit} className="space-y-3">
            {[
              { id: 'email', label: 'Email', type: 'email', value: email, setter: setEmail, placeholder: 'you@example.com' },
              { id: 'password', label: 'Password', type: 'password', value: password, setter: setPassword, placeholder: 'At least 8 characters' },
              { id: 'confirmPassword', label: 'Confirm password', type: 'password', value: confirmPassword, setter: setConfirmPassword, placeholder: 'Repeat password' },
              { id: 'inviteCode', label: 'Invite code', type: 'text', value: inviteCode, setter: setInviteCode, placeholder: 'Enter invite code' },
            ].map(({ id, label, type, value, setter, placeholder }) => (
              <div key={id}>
                <label
                  htmlFor={id}
                  style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '6px' }}
                >
                  {label}
                </label>
                <input
                  id={id}
                  type={type}
                  value={value}
                  onChange={(e) => setter(e.target.value)}
                  className="input-base w-full"
                  placeholder={placeholder}
                  required
                  autoFocus={id === 'email'}
                  disabled={isLoading}
                />
              </div>
            ))}

            {localError && (
              <div
                className="rounded-md px-3 py-2"
                style={{
                  backgroundColor: 'oklch(65% 0.20 25 / 0.1)',
                  border: '1px solid oklch(65% 0.20 25 / 0.3)',
                }}
              >
                <p style={{ fontSize: '13px', color: 'var(--c-error)' }}>{localError}</p>
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="btn-primary w-full"
              style={{ marginTop: '8px', justifyContent: 'center' }}
            >
              {isLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin h-3.5 w-3.5" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Creating account…
                </span>
              ) : (
                'Create account'
              )}
            </button>
          </form>
        </div>

        <p style={{ textAlign: 'center', marginTop: '16px', fontSize: '13px', color: 'var(--text-tertiary)' }}>
          Already have an account?{' '}
          <Link to="/login" style={{ color: 'var(--accent)', textDecoration: 'none', fontWeight: 500 }}>
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
};
