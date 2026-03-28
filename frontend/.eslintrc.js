import { defineConfig } from 'eslint-define-config'

export default defineConfig({
  baseConfig: {
    extends: ['@comic-pile/eslint-config'],
  },
  jiti: {
    createRequire: true,
  },
})
