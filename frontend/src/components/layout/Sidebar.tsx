import React, { Fragment } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Menu, Transition } from '@headlessui/react';
import {
  ArrowRightStartOnRectangleIcon,
  ArrowUpTrayIcon,
  ChevronUpIcon,
  ClockIcon,
  Cog6ToothIcon,
  MoonIcon,
  ShieldCheckIcon,
  SunIcon,
} from '@heroicons/react/24/outline';
import { useAuth } from '../../hooks/useAuth';
import { useSettings } from '../../hooks/useSettings';
import { useJobs } from '../../hooks/useJobs';
import { useTheme } from '../../hooks/useTheme';

interface NavItemProps {
  active?: boolean;
  icon: React.ReactNode;
  label: string;
  count?: number;
  onClick?: () => void;
  to?: string;
}

const BrandMark: React.FC = () => (
  <img className="brand-mark" src="/subtitle-icon.svg?v=2" width="32" height="32" alt="" aria-hidden="true" />
);

const NavItem: React.FC<NavItemProps> =({ active, icon, label, count, onClick, to }) => {
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
      <Link to={to} className={baseClass} title={label} aria-current={active ? 'page' : undefined}>
        {inner}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} className={baseClass} title={label}>
      {inner}
    </button>
  );
};

interface SidebarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ collapsed, onToggleCollapse }) => {
  const { user, logout } = useAuth();
  const { openSettings } = useSettings();
  const { activeJobCount, setShowJobPanel } = useJobs();
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();

  const onUploadPage = location.pathname === '/' && !new URLSearchParams(location.search).has('job');
  const isAdmin = location.pathname.startsWith('/admin');
  const themeLabel = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';

  const initials = (user?.display_name || user?.email || 'U')
    .split(/\s+/)
    .map((s) => s.charAt(0).toUpperCase())
    .slice(0, 2)
    .join('');

  return (
    <aside className={`sidebar ${collapsed ? 'is-collapsed' : ''}`}>
      <div className="sidebar-top">
        <Link to="/" className="brand" aria-label="AI Subs home">
          <BrandMark />
          <span className="brand-word">
            AI <span>Subs</span>
          </span>
        </Link>
        <button
          type="button"
          className="sidebar-collapse"
          onClick={onToggleCollapse}
          aria-label={collapsed ? 'Show sidebar' : 'Hide sidebar'}
          title={collapsed ? 'Show sidebar' : 'Hide sidebar'}
          aria-expanded={!collapsed}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <rect x="3.5" y="4.5" width="17" height="15" rx="3" />
            <path d="M9 5v14" />
            <path d={collapsed ? 'm13 9 3 3-3 3' : 'm16 9-3 3 3 3'} strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      <nav className="sidebar-nav" aria-label="Main">
        <NavItem
          to="/"
          active={onUploadPage}
          label="New video"
          icon={
            <ArrowUpTrayIcon aria-hidden="true" />
          }
        />

        <NavItem
          onClick={() => setShowJobPanel(true)}
          label="Jobs"
          count={activeJobCount}
          icon={
            <ClockIcon aria-hidden="true" />
          }
        />

        {user?.is_admin && (
          <NavItem
            to="/admin"
            active={isAdmin}
            label="Admin"
            icon={
              <ShieldCheckIcon aria-hidden="true" />
            }
          />
        )}
      </nav>

      <div style={{ flex: 1 }} />

      <div className="sidebar-foot">
        <Menu as="div" className="user-menu">
          <Menu.Button className="user-card">
            <div className="user-avatar">{initials}</div>
            <div className="user-who">
              <strong>{user?.display_name || 'User'}</strong>
              <span>{user?.email}</span>
            </div>
            <ChevronUpIcon className="user-caret" strokeWidth={2} aria-hidden="true" />
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
              className="sidebar-user-menu-items"
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
                    className="sidebar-user-menu-item block w-full text-left px-3 py-1.5 text-sm transition-colors duration-100"
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
                      className="sidebar-user-menu-item flex items-center gap-2 w-full text-left px-3 py-1.5 text-sm transition-colors duration-100"
                      style={{
                        color: 'var(--text-secondary)',
                        backgroundColor: active ? 'var(--bg-surface)' : 'transparent',
                      }}
                    >
                      <ArrowRightStartOnRectangleIcon className="w-3.5 h-3.5" aria-hidden="true" />
                      Sign out
                    </button>
                  )}
                </Menu.Item>
              </div>
            </Menu.Items>
          </Transition>
        </Menu>

        <div className="sidebar-foot-actions">
          <button
            type="button"
            className="sidebar-icon-btn"
            onClick={() => openSettings()}
            aria-label="Settings"
            title="Settings"
          >
            <Cog6ToothIcon aria-hidden="true" />
          </button>
          <button
            type="button"
            className="sidebar-icon-btn"
            onClick={toggleTheme}
            aria-label={themeLabel}
            title={themeLabel}
          >
            {theme === 'dark' ? (
              <SunIcon aria-hidden="true" />
            ) : (
              <MoonIcon aria-hidden="true" />
            )}
          </button>
        </div>
      </div>
    </aside>
  );
};
