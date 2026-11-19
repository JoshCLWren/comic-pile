import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { join } from './path.js';
const empty = join(fileURLToPath(import.meta.url), '../empty.js');
const options = {
    alias: {
        '@rushstack/eslint-config/patch/modern-module-resolution': empty,
        '@rushstack/eslint-patch/modern-module-resolution': empty,
    },
    tsconfigPaths: true,
    jsx: true,
    extensions: ['.js', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts', '.mtsx', '.ctsx', '.jsx'],
};
const cwd = process.cwd();
const require = createRequire(import.meta.url);
let jiti;
export const getJiti = () => {
    if (jiti)
        return jiti;
    const { createJiti } = require('jiti');
    return (jiti = createJiti(cwd, options));
};
