import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { AuthProvider } from './hooks/useAuth';
import { SettingsProvider } from './hooks/useSettings';
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
          <SettingsProvider>
            <Toaster
              position="top-right"
              toastOptions={{
                duration: 4000,
                style: {
                  background: '#fff',
                  color: '#1f2937',
                  boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
                },
                success: {
                  iconTheme: {
                    primary: '#10b981',
                    secondary: '#fff',
                  },
                },
                error: {
                  iconTheme: {
                    primary: '#ef4444',
                    secondary: '#fff',
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
        </AuthProvider>
      </Router>
    </QueryClientProvider>
  );
}

export default App;
