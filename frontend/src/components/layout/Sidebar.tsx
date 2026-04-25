/**
 * Sidebar — persistent left navigation, 240px wide.
 * Replaces the old top-bar nav with a richer IA: brand, primary nav,
 * tools, and a user card at the bottom.
 */

import React, { Fragment } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Menu, Transition } from '@headlessui/react';
import { useAuth } from '../../hooks/useAuth';
import { useSettings } from '../../hooks/useSettings';
import { useJobs } from '../../contexts/JobsContext';
import { useTheme } from '../../contexts/ThemeContext';

type NavKey = 'workspace' | 'jobs' | 'settings';

interface NavItemProps {
  active?: boolean;
  icon: React.ReactNode;
  label: string;
  count?: number;
  onClick?: () => void;
  to?: string;
}

const NavItem: React.FC<NavItemProps> = ({ active, icon, label, count, onClick, to }) => {
  const inner = (
    <>
      <span className="nav-item-icon">{icon}</span>
      <span className="nav-item-label">{label}</span>
      {typeof count === 'number' && count > 0 && (
        <span className="nav-item-count mono">{count}</span>
      )}
    </>
  );

  const baseClass = `nav-item ${active ? 'is-active' : ''}`;

  if (to) {
    return (
      <Link to={to} className={baseClass}>
        {inner}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} className={baseClass}>
      {inner}
    </button>
  );
};

export const Sidebar: React.FC = () => {
  const { user, logout } = useAuth();
  const { openSettings } = useSettings();
  const { activeJobCount, setShowJobPanel } = useJobs();
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();

  const isWorkspace = location.pathname === '/' || location.pathname.startsWith('/transcript');
  const isAdmin = location.pathname.startsWith('/admin');

  const initials = (user?.display_name || user?.email || 'U')
    .split(/\s+/)
    .map((s) => s.charAt(0).toUpperCase())
    .slice(0, 2)
    .join('');

  return (
    <aside className="sidebar">
      {/* Brand */}
      <Link to="/" className="brand" aria-label="AI Subs home">
        <span className="brand-mark" aria-hidden="true" />
        <span className="brand-word">
          AI <span>Subs</span>
        </span>
      </Link>

      {/* Workspace */}
      <div className="side-label">Workspace</div>

      <NavItem
        to="/"
        active={isWorkspace}
        label="Workspace"
        icon={
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8">
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
          </svg>
        }
      />

      <NavItem
        onClick={() => setShowJobPanel(true)}
        label="Jobs"
        count={activeJobCount}
        icon={
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8">
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M12 8v4l2.5 2.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        }
      />

      {user?.is_admin && (
        <NavItem
          to="/admin"
          active={isAdmin}
          label="Admin"
          icon={
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8">
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
          }
        />
      )}

      {/* Tools */}
      <div className="side-label">Tools</div>

      <NavItem
        onClick={() => openSettings()}
        label="Settings"
        icon={
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8">
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        }
      />

      <NavItem
        onClick={toggleTheme}
        label={theme === 'dark' ? 'Light mode' : 'Dark mode'}
        icon={
          theme === 'dark' ? (
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8">
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364-.707.707M6.343 17.657l-.707.707M17.657 17.657l-.707-.707M6.343 6.343l-.707-.707M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z" />
            </svg>
          ) : (
            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="1.8">
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M21.752 15.002A9.72 9.72 0 0 1 18 15.75 9.75 9.75 0 0 1 8.25 6c0-1.33.266-2.597.748-3.752A9.754 9.754 0 0 0 3 12c0 5.385 4.365 9.75 9.75 9.75 4.771 0 8.757-3.43 9.748-8z" />
            </svg>
          )
        }
      />

      {/* Spacer pushes user card to the bottom */}
      <div style={{ flex: 1 }} />

      {/* User card with menu */}
      <div className="sidebar-foot">
        <Menu as="div" className="user-menu">
          <Menu.Button className="user-card">
            <div className="user-avatar">{initials}</div>
            <div className="user-who">
              <strong>{user?.display_name || 'User'}</strong>
              <span>{user?.email}</span>
            </div>
            <svg className="user-caret" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 15l7-7 7 7" />
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
              className="absolute bottom-full mb-2 left-0 right-0 origin-bottom rounded-md z-50 py-1"
              style={{
                backgroundColor: 'var(--bg-overlay)',
                border: '1px solid var(--border-subtle)',
                boxShadow: 'var(--shadow-overlay)',
              }}
            >
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
    </aside>
  );
};

export type { NavKey };
