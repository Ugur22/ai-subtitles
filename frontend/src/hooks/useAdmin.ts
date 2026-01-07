/**
 * useAdmin - Admin operations hook
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import * as adminService from '../services/admin';

export const useAdmin = () => {
  const queryClient = useQueryClient();

  // Fetch users
  const {
    data: users = [],
    isLoading: isLoadingUsers,
    error: usersError,
  } = useQuery({
    queryKey: ['adminUsers'],
    queryFn: adminService.getUsers,
    retry: 1,
  });

  // Fetch invite codes
  const {
    data: inviteCodes = [],
    isLoading: isLoadingCodes,
    error: codesError,
  } = useQuery({
    queryKey: ['inviteCodes'],
    queryFn: adminService.getInviteCodes,
    retry: 1,
  });

  // Fetch stats
  const {
    data: stats,
    isLoading: isLoadingStats,
    error: statsError,
  } = useQuery({
    queryKey: ['adminStats'],
    queryFn: adminService.getAdminStats,
    retry: 1,
  });

  // Create invite code mutation
  const createCodeMutation = useMutation({
    mutationFn: adminService.createInviteCode,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['inviteCodes'] });
      toast.success(`Invite code created: ${data.code}`);
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to create invite code');
    },
  });

  // Delete invite code mutation
  const deleteCodeMutation = useMutation({
    mutationFn: adminService.deleteInviteCode,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['inviteCodes'] });
      toast.success('Invite code deleted');
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to delete invite code');
    },
  });

  // Delete user mutation
  const deleteUserMutation = useMutation({
    mutationFn: adminService.deleteUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] });
      queryClient.invalidateQueries({ queryKey: ['adminStats'] });
      toast.success('User deleted');
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to delete user');
    },
  });

  // Invalidate user keys mutation
  const invalidateKeysMutation = useMutation({
    mutationFn: adminService.invalidateUserKeys,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] });
      toast.success('User keys invalidated');
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to invalidate keys');
    },
  });

  return {
    users,
    inviteCodes,
    stats,
    isLoading: isLoadingUsers || isLoadingCodes || isLoadingStats,
    isLoadingUsers,
    isLoadingCodes,
    isLoadingStats,
    errors: {
      users: usersError,
      codes: codesError,
      stats: statsError,
    },
    createInviteCode: createCodeMutation.mutateAsync,
    deleteInviteCode: deleteCodeMutation.mutateAsync,
    deleteUser: deleteUserMutation.mutateAsync,
    invalidateUserKeys: invalidateKeysMutation.mutateAsync,
    isCreatingCode: createCodeMutation.isPending,
    isDeletingCode: deleteCodeMutation.isPending,
    isDeletingUser: deleteUserMutation.isPending,
    isInvalidatingKeys: invalidateKeysMutation.isPending,
  };
};
