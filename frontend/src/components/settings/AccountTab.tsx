/**
 * AccountTab - Account management (delete account)
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { deleteAccount } from '../../services/admin';
import { useAuth } from '../../hooks/useAuth';

export const AccountTab: React.FC = () => {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [isDeleting, setIsDeleting] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [showConfirm, setShowConfirm] = useState(false);

  const handleDeleteAccount = async () => {
    if (confirmText !== 'DELETE') {
      toast.error('Please type DELETE to confirm');
      return;
    }

    setIsDeleting(true);
    try {
      await deleteAccount();
      await logout();
      toast.success('Account deleted successfully');
      navigate('/login');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to delete account');
      setIsDeleting(false);
    }
  };

  return (
    <div className="space-y-6 p-4">
      <div>
        <h3 className="text-lg font-medium text-gray-900 mb-4">Account Management</h3>

        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg
                className="h-5 w-5 text-red-400"
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path
                  fillRule="evenodd"
                  d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
                  clipRule="evenodd"
                />
              </svg>
            </div>
            <div className="ml-3 flex-1">
              <h4 className="text-sm font-medium text-red-800 mb-2">Danger Zone</h4>
              <p className="text-sm text-red-700 mb-4">
                Deleting your account is permanent and cannot be undone. All your data,
                including transcriptions, API keys, and settings will be permanently deleted.
              </p>

              {!showConfirm ? (
                <button
                  onClick={() => setShowConfirm(true)}
                  className="btn-secondary border-red-300 text-red-700 hover:bg-red-50 hover:border-red-400"
                >
                  Delete Account
                </button>
              ) : (
                <div className="space-y-3">
                  <div>
                    <label
                      htmlFor="confirmDelete"
                      className="block text-sm font-medium text-red-800 mb-1"
                    >
                      Type <strong>DELETE</strong> to confirm
                    </label>
                    <input
                      id="confirmDelete"
                      type="text"
                      value={confirmText}
                      onChange={(e) => setConfirmText(e.target.value)}
                      className="input-base w-full border-red-300 focus:ring-red-500 focus:border-red-500"
                      placeholder="DELETE"
                      disabled={isDeleting}
                    />
                  </div>

                  <div className="flex gap-2">
                    <button
                      onClick={handleDeleteAccount}
                      disabled={isDeleting || confirmText !== 'DELETE'}
                      className="btn-primary bg-red-600 hover:bg-red-700 focus:ring-red-500 flex-1"
                    >
                      {isDeleting ? 'Deleting...' : 'Confirm Delete Account'}
                    </button>
                    <button
                      onClick={() => {
                        setShowConfirm(false);
                        setConfirmText('');
                      }}
                      disabled={isDeleting}
                      className="btn-secondary"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
