/**
 * LoginPage - Full page login form
 */

import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const { login, isLoading } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await login(email, password);
      navigate('/');
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

        {/* Logo mark */}
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
            Sign in
          </h1>
          <p style={{ fontSize: '13px', color: 'var(--text-tertiary)', marginBottom: '20px' }}>
            Enter your credentials to continue
          </p>

          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label
                htmlFor="email"
                style={{ display: 'block', fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)', marginBottom: '6px' }}
              >
                Email
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-base w-full"
                placeholder="you@example.com"
                required
                autoFocus
                disabled={isLoading}
              />
            </div>

            <div>
              <div className="flex items-center justify-between" style={{ marginBottom: '6px' }}>
                <label
                  htmlFor="password"
                  style={{ fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)' }}
                >
                  Password
                </label>
                <Link
                  to="/forgot-password"
                  style={{ fontSize: '12px', color: 'var(--accent)', textDecoration: 'none' }}
                >
                  Forgot password?
                </Link>
              </div>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-base w-full"
                placeholder="Enter password"
                required
                disabled={isLoading}
              />
            </div>

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
                  Signing in…
                </span>
              ) : (
                'Sign in'
              )}
            </button>
          </form>
        </div>

        <p style={{ textAlign: 'center', marginTop: '16px', fontSize: '13px', color: 'var(--text-tertiary)' }}>
          No account?{' '}
          <Link to="/register" style={{ color: 'var(--accent)', textDecoration: 'none', fontWeight: 500 }}>
            Sign up
          </Link>
        </p>
      </div>
    </div>
  );
};
