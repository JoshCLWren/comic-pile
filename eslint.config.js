import js from '@eslint/js';
import globals from 'globals';

export default [
  {
    files: ['static/js/app.js'],
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: 'script',
      globals: {
        ...globals.browser,
        'THREE': 'readonly',
        'Sortable': 'readonly',
        'Dice3D': 'readonly',
        'window': 'readonly',
        'document': 'readonly',
        'console': 'readonly',
        'setTimeout': 'readonly',
        'fetch': 'readonly',
        'alert': 'readonly',
        'confirm': 'readonly'
      }
    },
    rules: {
      'no-unused-vars': ['warn', { varsIgnorePattern: '^(calculateStaleness|loadQueue|initializeSortable|updateThreadPosition|moveThread|moveToFront|moveToBack|openEditModal|closeEditModal|deleteThread|openPositionModal)$' }],
      'no-console': 'off',
      'no-undef': 'error',
      'semi': ['error', 'always'],
      'quotes': ['error', 'single', { avoidEscape: true }],
      'indent': ['error', 4],
      'comma-dangle': ['error', 'never'],
      'prefer-const': 'warn',
      'eqeqeq': ['error', 'always'],
      'curly': ['warn', 'multi-line'],
      'space-before-blocks': 'error',
      'keyword-spacing': 'error',
      'indent': 'off',
      'no-multiple-empty-lines': ['error', { max: 2 }],
      'no-trailing-spaces': 'error'
    }
  },
  {
    files: ['static/js/dice3d.js'],
    languageOptions: {
      ecmaVersion: 2020,
      sourceType: 'module',
      globals: {
        ...globals.browser,
        'THREE': 'readonly',
        'window': 'readonly',
        'document': 'readonly',
        'console': 'readonly'
      }
    },
    rules: {
      'no-unused-vars': 'warn',
      'no-console': 'off',
      'no-undef': 'error',
      'semi': 'off',
      'quotes': ['warn', 'single', { avoidEscape: true }],
      'indent': 'off',
      'no-var': 'off',
      'prefer-const': 'off',
      'eqeqeq': ['warn', 'always'],
      'curly': 'off',
      'space-before-blocks': 'warn',
      'keyword-spacing': 'off',
      'space-infix-ops': 'off',
      'indent': 'off',
      'no-multiple-empty-lines': ['warn', { max: 2 }],
      'no-trailing-spaces': 'warn',
      'no-redeclare': 'off'
    }
  }
];
