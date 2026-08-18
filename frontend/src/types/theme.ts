/** Theme system types (Issue #1399). */

export type ThemeId = 'classic' | 'ink-gold' | 'command-center';

export const SUPPORTED_THEMES: readonly ThemeId[] = [
  'classic',
  'ink-gold',
  'command-center',
] as const;

export const DEFAULT_THEME: ThemeId = 'classic';

export interface UserPreferences {
  theme: ThemeId;
  user_id: number;
}

export interface UserPreferencesPatchRequest {
  theme?: ThemeId;
}

export function isValidThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && SUPPORTED_THEMES.includes(value as ThemeId);
}
