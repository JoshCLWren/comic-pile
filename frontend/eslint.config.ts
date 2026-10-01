import js from '@eslint/js'
import globals from 'globals'
import tsEslintPlugin from '@typescript-eslint/eslint-plugin'
import tsEslintParser from '@typescript-eslint/parser'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import {
  findGridColsArbitraryComma,
  gridColsArbitraryCommaMessage,
} from './eslint-rules/grid-cols-comma-guard.ts'

/**
 * Custom rule to prevent direct React Query cache mutations outside cacheEffects.ts
 */
const noDirectCacheMutationsPlugin = {
  rules: {
    'no-direct-cache-mutations': {
      meta: {
        type: 'problem',
        docs: {
          description: 'Prevent direct React Query cache mutations outside cacheEffects.ts',
          recommended: 'error',
        },
        schema: [],
        messages: {
          directCacheMutation: 'Direct React Query cache mutations are only allowed in cacheEffects.ts or test files.',
        },
      },
create(context) {
    const cacheEffectsPath = 'src/query/cacheEffects.ts'
    const isCacheEffectsFile = context.filename?.endsWith(cacheEffectsPath)
    const isTestFile = context.filename?.includes('/test/') || context.filename?.includes('/unit/') || context.filename?.includes('/e2e/')
    // useRollBootstrap.ts reconciliation events intentionally use direct setQueryData for real-time reconciliation
    const isRollBootstrapFile = context.filename?.endsWith('src/hooks/useRollBootstrap.ts')

        return {
          CallExpression(node) {
            if (isCacheEffectsFile || isTestFile || isRollBootstrapFile) return

            const callee = node.callee
            if (callee.type === 'MemberExpression') {
              const object = callee.object
              const property = callee.property

              if (
                object.type === 'Identifier' &&
                object.name === 'queryClient' &&
                property.type === 'Identifier' &&
                ['setQueryData', 'invalidateQueries', 'removeQueries'].includes(property.name)
              ) {
                context.report({
                  node,
                  messageId: 'directCacheMutation',
                })
              }
            }
          },
        }
      },
    },
  },
}

/**
 * Custom rule banning Tailwind arbitrary `grid-cols-[...]` track lists that
 * use commas (the #2952 failure mode: `grid-cols-[1fr,auto]` emits invalid
 * CSS and the grid silently collapses). Underscore-separated tracks and
 * commas inside CSS functions such as `minmax(0,1fr)` remain allowed.
 * Detection lives in `./eslint-rules/grid-cols-comma-guard` so the vitest
 * suite can cover the same predicate. CI bar owned by #2992.
 */
const noGridColsArbitraryCommasPlugin = {
  rules: {
    'no-grid-cols-arbitrary-commas': {
      meta: {
        type: 'problem',
        docs: {
          description:
            'Ban Tailwind arbitrary grid-cols tracks with commas; use underscores instead',
          recommended: 'error',
        },
        schema: [],
        messages: {
          gridColsComma: '{{message}}',
        },
      },
      create(context) {
        // String() normalizes any literal value to scannable text: string
        // literals pass through unchanged, while numbers/booleans/null can
        // never spell a grid-cols token. This keeps the visitor free of
        // runtime typeof narrowing (see anti-slop/no-runtime-typeof).
        const reportIfOffending = (text, node) => {
          const offending = findGridColsArbitraryComma(String(text))
          if (offending !== null) {
            context.report({
              node,
              messageId: 'gridColsComma',
              data: { message: gridColsArbitraryCommaMessage(offending) },
            })
          }
        }

        return {
          Literal(node) {
            reportIfOffending(node.value, node)
          },
          TemplateElement(node) {
            reportIfOffending(node.value.cooked, node)
          },
        }
      },
    },
  },
}

export default [
  {
    ignores: ['dist', 'coverage'],
  },
  {
    files: ['**/*.{js,jsx,ts,tsx}'],
    plugins: {
      'no-direct-cache-mutations': noDirectCacheMutationsPlugin,
      'no-grid-cols-arbitrary-commas': noGridColsArbitraryCommasPlugin,
    },
    rules: {
      'no-direct-cache-mutations/no-direct-cache-mutations': 'error',
      'no-grid-cols-arbitrary-commas/no-grid-cols-arbitrary-commas': 'error',
    },
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
      '@typescript-eslint': tsEslintPlugin,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      'no-unused-vars': 'off',
      'max-lines': ['error', { max: 1200, skipBlankLines: true, skipComments: true }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          varsIgnorePattern: '^[A-Z_]',
          argsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
    },
  },
  {
    files: ['src/generated/**/*.{ts,tsx}'],
    rules: {
      'max-lines': 'off',
    },
  },
  {
    files: ['src/test/**/*.{ts,tsx}', 'src/unit/**/*.{ts,tsx}'],
    rules: {
      'max-lines': ['error', { max: 1600, skipBlankLines: true, skipComments: true }],
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
