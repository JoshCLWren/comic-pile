import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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
});