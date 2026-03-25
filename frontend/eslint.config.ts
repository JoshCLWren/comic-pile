import js from '@eslint/js'
import globals from 'globals'
// Types for optional tooling (fallback if not installed in environment)
let tsEslintPlugin: any = undefined
let tsEslintParser: any = undefined
let reactHooks: any = undefined
let reactRefresh: any = undefined
try {
  tsEslintPlugin = require('@typescript-eslint/eslint-plugin')
} catch {
  tsEslintPlugin = undefined
}
try {
  tsEslintParser = require('@typescript-eslint/parser')
} catch {
  tsEslintParser = undefined
}
try {
  reactHooks = require('eslint-plugin-react-hooks')
} catch {
  reactHooks = undefined
}
try {
  reactRefresh = require('eslint-plugin-react-refresh')
} catch {
  reactRefresh = undefined
}
 

export default [
  {
    ignores: ['dist'],
  },
  {
    files: ['**/*.{js,jsx,ts,tsx}'],
    ...js.configs.recommended,
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parser: tsEslintParser,
      parserOptions: {
        ecmaVersion: 'latest',
        ecmaFeatures: { jsx: true },
        sourceType: 'module',
      },
    },
    plugins: {
      ...(tsEslintPlugin ? { '@typescript-eslint': tsEslintPlugin } : {}),
      ...(reactHooks ? { 'react-hooks': reactHooks } : {}),
      ...(reactRefresh ? { 'react-refresh': reactRefresh } : {}),
    },
    rules: {
      ...(tsEslintPlugin
        ? {
            '@typescript-eslint/no-unused-vars': [
              'error',
              {
                varsIgnorePattern: '^[A-Z_]',
                argsIgnorePattern: '^_',
                caughtErrorsIgnorePattern: '^_',
              },
            ],
          }
        : {}),
      ...(reactHooks ? { 'react-hooks/rules-of-hooks': 'error', 'react-hooks/exhaustive-deps': 'warn' } : {}),
      ...(reactRefresh ? { 'react-refresh/only-export-components': ['warn', { allowConstantExport: true }] } : {}),
      'no-unused-vars': 'off',
      'max-lines': ['error', { max: 1000, skipBlankLines: true, skipComments: true }],
    },
  },
  {
    files: ['src/test/**/*.{ts,tsx}'],
    rules: {
      'react-hooks/rules-of-hooks': 'off',
      'react-hooks/exhaustive-deps': 'off',
    },
  },
  {
    files: ['src/contexts/CollectionContext.tsx'],
    rules: {
      'react-refresh/only-export-components': 'off',
    },
  },
  {
    files: ['src/test/**/*.spec.ts', 'e2e/**/*.spec.ts'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.node,
      parser: tsEslintParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
    },
    rules: {
      '@typescript-eslint/no-unused-vars': 'off',
      'no-console': 'off',
    },
  },
]
