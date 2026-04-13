import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { AuthProvider } from './hooks/useAuth';
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

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <AuthProvider>
          <JobsProvider>
          <SettingsProvider>
            <Toaster
              position="top-right"
              toastOptions={{
                duration: 4000,
                style: {
                  background: 'oklch(17% 0.010 250)',
                  color: 'oklch(93% 0.005 250)',
                  border: '1px solid oklch(24% 0.012 250)',
                  boxShadow: '0 4px 16px oklch(0% 0 0 / 0.4)',
                  fontFamily: "'DM Sans', system-ui, sans-serif",
                  fontSize: '14px',
                },
                success: {
                  iconTheme: {
                    primary: 'oklch(70% 0.15 145)',
                    secondary: 'oklch(17% 0.010 250)',
                  },
                },
                error: {
                  iconTheme: {
                    primary: 'oklch(65% 0.20 25)',
                    secondary: 'oklch(17% 0.010 250)',
                  },
                },
              }}
            />
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
  );
}

export default App;
