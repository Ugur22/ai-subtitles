/**
 * Header - Main application header
 */

import React, { Fragment } from 'react';
import { Link } from 'react-router-dom';
import { Menu, Transition } from '@headlessui/react';
import { useAuth } from '../../hooks/useAuth';
import { useSettings } from '../../hooks/useSettings';
import { useJobs } from '../../contexts/JobsContext';

export const Header: React.FC = () => {
  const { user, logout } = useAuth();
  const { openSettings } = useSettings();
  const { activeJobCount, setShowJobPanel } = useJobs();

  return (
    <>
      <header
        style={{
          backgroundColor: 'var(--bg-subtle)',
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-12">

            {/* Logo */}
            <Link to="/" className="flex items-center">
              <span
                style={{
                  fontWeight: 600,
                  fontSize: '15px',
                  letterSpacing: '-0.01em',
                  color: 'var(--text-primary)',
                }}
              >
                AI Subs
              </span>
            </Link>

            {/* Right side */}
            <div className="flex items-center gap-1">

              {/* Jobs indicator */}
              <button
                onClick={() => setShowJobPanel(true)}
                style={{ color: 'var(--text-secondary)', position: 'relative' }}
                className="btn-ghost p-2 rounded-md"
                title="Transcription history"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M12 8v4l2.5 2.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                {activeJobCount > 0 && (
                  <span
                    style={{
                      position: 'absolute',
                      top: '4px',
                      right: '4px',
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      backgroundColor: 'var(--accent)',
                    }}
                  />
                )}
              </button>

              {/* Settings */}
              <button
                onClick={() => openSettings()}
                style={{ color: 'var(--text-secondary)' }}
                className="btn-ghost p-2 rounded-md"
                title="Settings"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                </svg>
              </button>

              {/* User menu */}
              <Menu as="div" className="relative ml-1">
                <Menu.Button
                  className="flex items-center gap-2 px-2 py-1.5 rounded-md transition-colors duration-150 hover:bg-[var(--bg-surface)]"
                  style={{ color: 'var(--text-secondary)' }}
                >
                  <div
                    style={{
                      width: '26px',
                      height: '26px',
                      borderRadius: '50%',
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-default)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '11px',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      flexShrink: 0,
                    }}
                  >
                    {user?.email?.charAt(0).toUpperCase()}
                  </div>
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </Menu.Button>

                <Transition
                  as={Fragment}
                  enter="transition ease-out duration-100"
                  enterFrom="transform opacity-0 scale-95"
                  enterTo="transform opacity-100 scale-100"
                  leave="transition ease-in duration-75"
                  leaveFrom="transform opacity-100 scale-100"
                  leaveTo="transform opacity-0 scale-95"
                >
                  <Menu.Items
                    className="absolute right-0 mt-1 w-52 origin-top-right rounded-md z-50 py-1"
                    style={{
                      backgroundColor: 'var(--bg-overlay)',
                      border: '1px solid var(--border-subtle)',
                      boxShadow: '0 8px 24px oklch(0% 0 0 / 0.5)',
                    }}
                  >
                    <div
                      className="px-3 py-2 mb-1"
                      style={{ borderBottom: '1px solid var(--border-subtle)' }}
                    >
                      <p style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)' }}>
                        {user?.display_name || 'User'}
                      </p>
                      <p style={{ fontSize: '12px', color: 'var(--text-tertiary)' }} className="truncate">
                        {user?.email}
                      </p>
                    </div>

                    {user?.is_admin && (
                      <Menu.Item>
                        {({ active }) => (
                          <Link
                            to="/admin"
                            className="block px-3 py-1.5 text-sm transition-colors duration-100"
                            style={{
                              color: 'var(--text-secondary)',
                              backgroundColor: active ? 'var(--bg-surface)' : 'transparent',
                            }}
                          >
                            Admin Dashboard
                          </Link>
                        )}
                      </Menu.Item>
                    )}

                    <Menu.Item>
                      {({ active }) => (
                        <button
                          onClick={() => openSettings('profile')}
                          className="block w-full text-left px-3 py-1.5 text-sm transition-colors duration-100"
                          style={{
                            color: 'var(--text-secondary)',
                            backgroundColor: active ? 'var(--bg-surface)' : 'transparent',
                          }}
                        >
                          Profile settings
                        </button>
                      )}
                    </Menu.Item>

                    <div style={{ borderTop: '1px solid var(--border-subtle)', marginTop: '4px', paddingTop: '4px' }}>
                      <Menu.Item>
                        {({ active }) => (
                          <button
                            onClick={() => logout()}
                            className="flex items-center gap-2 w-full text-left px-3 py-1.5 text-sm transition-colors duration-100"
                            style={{
                              color: 'var(--text-secondary)',
                              backgroundColor: active ? 'var(--bg-surface)' : 'transparent',
                            }}
                          >
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                                d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                            </svg>
                            Sign out
                          </button>
                        )}
                      </Menu.Item>
                    </div>
                  </Menu.Items>
                </Transition>
              </Menu>
            </div>
          </div>
        </div>
      </header>

    </>
  );
};
