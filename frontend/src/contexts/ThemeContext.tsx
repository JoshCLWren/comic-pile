import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { ThemeId, DEFAULT_THEME, isValidThemeId, SUPPORTED_THEMES } from '../types/theme';
import type { UserPreferences } from '../types';
import api from '../services/api';

interface ThemeContextValue {
  theme: ThemeId;
  isLoading: boolean;
  setTheme: (theme: ThemeId) => Promise<void>;
  supportedThemes: readonly ThemeId[];
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}

interface ThemeProviderProps {
  children: ReactNode;
  initialTheme?: ThemeId;
}

export function ThemeProvider({ children, initialTheme = DEFAULT_THEME }: ThemeProviderProps) {
  const [theme, setThemeState] = useState<ThemeId>(initialTheme);
  const [isLoading, setIsLoading] = useState(true);
  const [isApplying, setIsApplying] = useState(false);

  const applyTheme = useCallback((newTheme: ThemeId) => {
    document.documentElement.setAttribute('data-theme', newTheme);
  }, []);

  const setTheme = useCallback(async (newTheme: ThemeId) => {
    if (!isValidThemeId(newTheme)) {
      console.error(`Invalid theme id: ${newTheme}`);
      return;
    }

    setIsApplying(true);
    try {
      await api.patch<UserPreferences>('/users/me/preferences', { theme: newTheme });
      setThemeState(newTheme);
      applyTheme(newTheme);
    } catch (error) {
      console.error('Failed to persist theme preference:', error);
      throw error;
    } finally {
      setIsApplying(false);
    }
  }, [applyTheme]);

  useEffect(() => {
    if (isValidThemeId(initialTheme)) {
      applyTheme(initialTheme);
    }
    setIsLoading(false);
  }, [initialTheme, applyTheme]);

  return (
    <ThemeContext.Provider value={{ theme, isLoading, setTheme, supportedThemes: SUPPORTED_THEMES }}>
      {children}
    </ThemeContext.Provider>
  );
}