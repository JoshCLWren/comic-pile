import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { BrowserRouter, MemoryRouter, Routes, Route } from 'react-router-dom';
import ResetPasswordPage from '../pages/ResetPasswordPage';
import api from '../services/api';

vi.mock('../services/api');

const mockApi = vi.mocked(api);

const renderPage = (search = '?token=valid-token') => {
  return render(
    <MemoryRouter initialEntries={[`/reset-password${search}`]}>
      <Routes>
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/login" element={<div data-testid="login-page">Login Page</div>} />
        <Route path="/forgot-password" element={<div data-testid="forgot-page">Forgot Page</div>} />
      </Routes>
    </MemoryRouter>
  );
};

describe('ResetPasswordPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders error state when no token in URL', () => {
    renderPage('');

    expect(screen.getByRole('heading', { name: /invalid reset link/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /request a new reset link/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /back to login/i })).toBeInTheDocument();
    expect(screen.queryByLabelText(/new password/i)).not.toBeInTheDocument();
  });

  it('renders the reset form when token is present', () => {
    renderPage('?token=valid-token');

    expect(screen.getByRole('heading', { name: /reset password/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/new password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm new password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reset password/i })).toBeInTheDocument();
  });

  it('shows error when new password is empty', async () => {
    renderPage('?token=valid-token');

    const submitButton = screen.getByRole('button', { name: /reset password/i });
    await act(async () => {
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(screen.getByText('Password is required')).toBeInTheDocument();
    });
  });

  it('shows error when password is too short', async () => {
    renderPage('?token=valid-token');

    const newPasswordInput = screen.getByLabelText(/new password/i);
    const confirmPasswordInput = screen.getByLabelText(/confirm new password/i);
    const submitButton = screen.getByRole('button', { name: /reset password/i });

    await act(async () => {
      fireEvent.change(newPasswordInput, { target: { value: 'abc' } });
      fireEvent.change(confirmPasswordInput, { target: { value: 'abc' } });
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(screen.getByText('Password must be at least 6 characters')).toBeInTheDocument();
    });
  });

  it('shows error when passwords do not match', async () => {
    renderPage('?token=valid-token');

    const newPasswordInput = screen.getByLabelText(/new password/i);
    const confirmPasswordInput = screen.getByLabelText(/confirm new password/i);
    const submitButton = screen.getByRole('button', { name: /reset password/i });

    await act(async () => {
      fireEvent.change(newPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.change(confirmPasswordInput, { target: { value: 'DifferentPassword1!' } });
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(screen.getByText('Passwords do not match')).toBeInTheDocument();
    });
  });

  it('calls API and navigates to login on success', async () => {
    mockApi.post.mockResolvedValue({ message: 'Password reset successful' });

    renderPage('?token=valid-token');

    const newPasswordInput = screen.getByLabelText(/new password/i);
    const confirmPasswordInput = screen.getByLabelText(/confirm new password/i);
    const submitButton = screen.getByRole('button', { name: /reset password/i });

    await act(async () => {
      fireEvent.change(newPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.change(confirmPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(screen.getByTestId('login-page')).toBeInTheDocument();
    });

    expect(mockApi.post).toHaveBeenCalledWith('/v1/auth/reset-password', {
      token: 'valid-token',
      new_password: 'NewPassword1!',
    });
  });

  it('shows error for expired token', async () => {
    mockApi.post.mockRejectedValue({
      response: { data: { detail: 'Token has expired' }, status: 400 },
    });
    
    renderPage('?token=valid-token');


    const newPasswordInput = screen.getByLabelText(/new password/i);
    const confirmPasswordInput = screen.getByLabelText(/confirm new password/i);
    const submitButton = screen.getByRole('button', { name: /reset password/i });

    await act(async () => {
      fireEvent.change(newPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.change(confirmPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(screen.getByText('This reset link has expired, been used, or is invalid. Please request a new reset link from the login page.')).toBeInTheDocument();
    });
  });

  it('shows error for invalid token', async () => {
    mockApi.post.mockRejectedValue({
      response: { data: { detail: 'Invalid or expired token' }, status: 400 },
    });
    
    renderPage('?token=valid-token');


    const newPasswordInput = screen.getByLabelText(/new password/i);
    const confirmPasswordInput = screen.getByLabelText(/confirm new password/i);
    const submitButton = screen.getByRole('button', { name: /reset password/i });

    await act(async () => {
      fireEvent.change(newPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.change(confirmPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(screen.getByText('This reset link has expired, been used, or is invalid. Please request a new reset link from the login page.')).toBeInTheDocument();
    });
  });

  it('shows error for already used token', async () => {
    mockApi.post.mockRejectedValue({
      response: { data: { detail: 'Token has already been used' }, status: 400 },
    });
    
    renderPage('?token=valid-token');


    const newPasswordInput = screen.getByLabelText(/new password/i);
    const confirmPasswordInput = screen.getByLabelText(/confirm new password/i);
    const submitButton = screen.getByRole('button', { name: /reset password/i });

    await act(async () => {
      fireEvent.change(newPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.change(confirmPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(screen.getByText('This reset link has expired, been used, or is invalid. Please request a new reset link from the login page.')).toBeInTheDocument();
    });
  });

  it('shows error for rate limited', async () => {
    mockApi.post.mockRejectedValue({
      response: { data: { detail: 'Too many attempts' }, status: 429 },
    });

    renderPage('?token=valid-token');

    const newPasswordInput = screen.getByLabelText(/new password/i);
    const confirmPasswordInput = screen.getByLabelText(/confirm new password/i);
    const submitButton = screen.getByRole('button', { name: /reset password/i });

    await act(async () => {
      fireEvent.change(newPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.change(confirmPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(screen.getByText('Too many attempts. Please try again later.')).toBeInTheDocument();
    });
  });

  it('shows generic error when API fails without detail', async () => {
    mockApi.post.mockRejectedValue(new Error('Network error'));

    renderPage('?token=valid-token');

    const newPasswordInput = screen.getByLabelText(/new password/i);
    const confirmPasswordInput = screen.getByLabelText(/confirm new password/i);
    const submitButton = screen.getByRole('button', { name: /reset password/i });

    await act(async () => {
      fireEvent.change(newPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.change(confirmPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(screen.getByText('Something went wrong. Please try again.')).toBeInTheDocument();
    });
  });

  it('disables button during submission', async () => {
    let resolveFn: (value: unknown) => void;
    mockApi.post.mockImplementation(() => new Promise((resolve) => { resolveFn = resolve; }));

    renderPage('?token=valid-token');

    const newPasswordInput = screen.getByLabelText(/new password/i);
    const confirmPasswordInput = screen.getByLabelText(/confirm new password/i);
    const submitButton = screen.getByRole('button', { name: /reset password/i });

    await act(async () => {
      fireEvent.change(newPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.change(confirmPasswordInput, { target: { value: 'NewPassword1!' } });
      fireEvent.click(submitButton);
    });

    await waitFor(() => {
      expect(submitButton).toBeDisabled();
      expect(submitButton).toHaveTextContent('Resetting...');
    });

    await act(async () => {
      resolveFn!({ message: 'Password reset successful' });
    });
  });
});