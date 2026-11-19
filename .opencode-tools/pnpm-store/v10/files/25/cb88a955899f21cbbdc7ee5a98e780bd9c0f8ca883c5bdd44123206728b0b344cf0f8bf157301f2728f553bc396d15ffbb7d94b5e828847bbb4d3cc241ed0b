import { toModule, toDependency, toIgnore, toEntry } from '../../util/input.js';
import { isInternal, join } from '../../util/path.js';
import { hasDependency } from '../../util/plugin.js';
const title = 'Nitro';
const enablers = ['nitropack', 'nitro'];
const isEnabled = ({ dependencies }) => hasDependency(dependencies, enablers);
const config = ['nitro.config.{js,cjs,mjs,ts,cts,mts}'];
const production = [
    'server.{js,mjs,ts}',
    'api/**/*.ts',
    'routes/**/*.ts',
    'middleware/**/*.ts',
    'plugins/**/*.ts',
    '.nitro/types/*.d.ts',
];
const setup = async () => {
    if (globalThis && !('defineNitroConfig' in globalThis)) {
        Object.defineProperty(globalThis, 'defineNitroConfig', {
            value: (id) => id,
            writable: true,
            configurable: true,
        });
    }
};
const resolve = () => [toIgnore('^#nitro-internal-', 'unresolved')];
const resolveConfig = async (localConfig) => {
    const srcDir = localConfig.srcDir ?? '.';
    const patterns = [
        toEntry('.nitro/types/*.d.ts', { production: true }),
        ...[
            typeof localConfig.serverEntry === 'string' ? localConfig.serverEntry : 'server.{js,mjs,ts}',
            join(typeof localConfig.apiDir === 'string' ? localConfig.apiDir : 'api', '**/*.ts'),
            join(typeof localConfig.routesDir === 'string' ? localConfig.routesDir : 'routes', '**/*.ts'),
            'middleware/**/*.ts',
            'plugins/**/*.ts',
        ].map(pattern => toEntry(join(srcDir, pattern), { production: true })),
    ];
    const deps = localConfig.modules?.reduce((acc, mod) => {
        const id = Array.isArray(mod) ? mod[0] : mod;
        if (typeof id === 'string')
            acc.push(isInternal(id) ? toModule(id) : toDependency(id));
        return acc;
    }, []) ?? [];
    return [...deps, ...patterns];
};
const note = `Knip works best with [manual imports](https://nitro.build/guide/utils#manual-imports).
Nitro allows you to disable auto-imports by setting \`imports: false\` in your Nitro config.`;
export const docs = { note };
const plugin = {
    title,
    enablers,
    isEnabled,
    config,
    production,
    setup,
    resolve,
    resolveConfig,
};
export default plugin;
