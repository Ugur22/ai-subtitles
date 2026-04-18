import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { AuthProvider } from './hooks/useAuth';
import { ThemeProvider, useTheme } from './contexts/ThemeContext';
import { SettingsProvider } from './hooks/useSettings';
import { JobsProvider } from './contexts/JobsContext';
import { ProtectedRoute } from './components/auth/ProtectedRoute';
import { LoginPage } from './components/auth/LoginPage';
import { RegisterPage } from './components/auth/RegisterPage';
import { VerifyEmailPage } from './components/auth/VerifyEmailPage';
import { ForgotPasswordPage } from './components/auth/ForgotPasswordPage';
import { ResetPasswordPage } from './components/auth/ResetPasswordPage';
import { MainLayout } from './components/layout/MainLayout';
import { TranscriptionUpload } from './components/features/transcription/TranscriptionUpload';
import { AdminDashboard } from './components/admin/AdminDashboard';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function DynamicToaster() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  return (
    <Toaster
      position="top-right"
      toastOptions={{
        duration: 4000,
        style: {
          background: 'var(--bg-subtle)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border-default)',
          boxShadow: `0 4px 16px oklch(0% 0 0 / ${isDark ? '0.4' : '0.15'})`,
          fontFamily: "'DM Sans', system-ui, sans-serif",
          fontSize: '14px',
        },
        // Icon colors mirror --c-success / --c-error tokens.
        // Inlined as oklch because react-hot-toast doesn't resolve CSS vars in icon SVG fills.
        success: {
          iconTheme: {
            primary: isDark ? 'oklch(70% 0.15 145)' : 'oklch(38% 0.15 145)',
            secondary: isDark ? 'oklch(17% 0.010 250)' : 'oklch(93.5% 0.008 250)',
          },
        },
        error: {
          iconTheme: {
            primary: isDark ? 'oklch(65% 0.20 25)' : 'oklch(52% 0.22 25)',
            secondary: isDark ? 'oklch(17% 0.010 250)' : 'oklch(93.5% 0.008 250)',
          },
        },
      }}
    />
  );
}

function App() {
  return (
    <ThemeProvider>
    <QueryClientProvider client={queryClient}>
      <Router>
        <AuthProvider>
          <JobsProvider>
          <SettingsProvider>
            <DynamicToaster />
            <Routes>
              {/* Public routes */}
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/verify-email" element={<VerifyEmailPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/reset-password" element={<ResetPasswordPage />} />

              {/* Protected routes */}
              <Route element={<ProtectedRoute />}>
                <Route
                  path="/"
                  element={
                    <MainLayout>
                      <TranscriptionUpload />
                    </MainLayout>
                  }
                />
                <Route path="/admin" element={<AdminDashboard />} />
              </Route>

              {/* Catch all - redirect to home */}
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </SettingsProvider>
          </JobsProvider>
        </AuthProvider>
      </Router>
    </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
