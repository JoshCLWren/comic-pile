import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import ForgotPasswordPage from '../pages/ForgotPasswordPage';
import api from '../services/api';

vi.mock('../services/api');

const _mockApi = vi.mocked(api);

const renderPage = () => {
  return render(
    <BrowserRouter>
      <ForgotPasswordPage />
    </BrowserRouter>
  );
};

describe('ForgotPasswordPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the page with correct heading and form elements', () => {
    renderPage();

    expect(screen.getByRole('heading', { name: /forgot password/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /send reset link/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /back to login/i })).toBeInTheDocument();
  });

  it('renders email input with placeholder', () => {
    renderPage();

    const emailInput = screen.getByLabelText(/email address/i);
    expect(emailInput).toHaveAttribute('placeholder', 'you@example.com');
    expect(emailInput).toHaveAttribute('type', 'email');
    expect(emailInput).toHaveAttribute('autocomplete', 'email');
  });

  it('renders form with submit button', () => {
    renderPage();

    expect(screen.getByRole('button', { name: /send reset link/i })).toBeInTheDocument();
    expect(screen.getByTestId('forgot-password-form')).toBeInTheDocument();
  });

  it('renders back to login link', () => {
    renderPage();

    expect(screen.getByRole('link', { name: /back to login/i })).toHaveAttribute('href', '/login');
  });

  it('submits a valid email to the forgot-password endpoint', async () => {
    _mockApi.post.mockResolvedValue({ message: 'ok' });

    renderPage();

    const form = screen.getByTestId('forgot-password-form');

    await act(async () => {
      fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: 'user@example.com' } });
      fireEvent.submit(form);
    });

    await waitFor(() => {
      expect(_mockApi.post).toHaveBeenCalledWith('/v1/auth/forgot-password', {
        email: 'user@example.com',
      });
    });

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /check your email/i })).toBeInTheDocument();
    });
  });

  it('shows a validation error without calling the API for an invalid email', async () => {
    renderPage();

    const form = screen.getByTestId('forgot-password-form');

    await act(async () => {
      fireEvent.change(screen.getByLabelText(/email address/i), { target: { value: 'not-an-email' } });
      fireEvent.submit(form);
    });

    await waitFor(() => {
      expect(screen.getByText('Please enter a valid email address')).toBeInTheDocument();
    });
    expect(_mockApi.post).not.toHaveBeenCalled();
  });
});