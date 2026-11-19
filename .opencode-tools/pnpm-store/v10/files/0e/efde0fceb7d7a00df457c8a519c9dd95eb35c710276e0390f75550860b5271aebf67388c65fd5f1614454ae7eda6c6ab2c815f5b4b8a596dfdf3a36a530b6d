import { toEntry } from '../../util/input.js';
import { createFsPromisesGlobVisitor } from './visitors/fsPromisesGlob.js';
const title = 'Node.js';
const isEnabled = () => true;
const patterns = [
    '**/*{.,-,_}test.{cjs,mjs,js,cts,mts,ts}',
    '**/test-*.{cjs,mjs,js,cts,mts,ts}',
    '**/test.{cjs,mjs,js,cts,mts,ts}',
    '**/test/**/*.{cjs,mjs,js,cts,mts,ts}',
];
const hasNodeTestCache = new WeakMap();
const hasNodeTest = (scripts, cwd, getScriptCommands) => {
    if (!scripts)
        return false;
    const cached = hasNodeTestCache.get(scripts);
    if (cached !== undefined)
        return cached;
    const result = Object.values(scripts).some(script => typeof script === 'string' &&
        getScriptCommands(script, cwd).some(({ binary, args }) => (binary === 'node' || binary === 'nub') && args.includes('--test')));
    hasNodeTestCache.set(scripts, result);
    return result;
};
const entry = ['server.js'];
const registerVisitors = ({ ctx, registerVisitor }) => {
    registerVisitor(createFsPromisesGlobVisitor(ctx));
};
const resolve = options => {
    const entries = entry.map(id => toEntry(id, { production: true }));
    if (hasNodeTest(options.manifest.scripts, options.cwd, options.getScriptCommands) ||
        hasNodeTest(options.rootManifest?.scripts, options.rootCwd, options.getScriptCommands)) {
        entries.push(...patterns.map(id => toEntry(id)));
    }
    return entries;
};
const toScripts = (parsed) => {
    if (parsed.eval !== undefined || parsed.print !== undefined || parsed.run !== undefined)
        return [];
    const scripts = parsed.test ? parsed._ : parsed._.slice(parsed._[0] === 'inspect' ? 1 : 0).slice(0, 1);
    return scripts.filter(script => !String(script).startsWith('-'));
};
export const args = {
    positional: toScripts,
    nodeImportArgs: true,
    resolve: ['test-reporter'],
    string: [
        'allow-fs-read',
        'allow-fs-write',
        'build-snapshot-config',
        'conditions',
        'cpu-prof-dir',
        'cpu-prof-interval',
        'cpu-prof-name',
        'debug-port',
        'diagnostic-dir',
        'disable-proto',
        'disable-warning',
        'dns-result-order',
        'env-file',
        'env-file-if-exists',
        'eval',
        'experimental-config-file',
        'experimental-default-config-file',
        'experimental-package-map',
        'experimental-sea-config',
        'experimental-test-isolation',
        'experimental-test-tag-filter',
        'heap-prof-dir',
        'heap-prof-interval',
        'heap-prof-name',
        'heapsnapshot-near-heap-limit',
        'heapsnapshot-signal',
        'icu-data-dir',
        'input-type',
        'inspect-port',
        'inspect-publish-uid',
        'localstorage-file',
        'max-http-header-size',
        'max-old-space-size-percentage',
        'network-family-autoselection-attempt-timeout',
        'openssl-config',
        'print',
        'redirect-warnings',
        'report-dir',
        'report-directory',
        'report-filename',
        'report-signal',
        'run',
        'secure-heap',
        'secure-heap-min',
        'security-revert',
        'security-reverts',
        'snapshot-blob',
        'stack-trace-limit',
        'test-concurrency',
        'test-coverage-branches',
        'test-coverage-exclude',
        'test-coverage-functions',
        'test-coverage-include',
        'test-coverage-lines',
        'test-global-setup',
        'test-isolation',
        'test-name-pattern',
        'test-random-seed',
        'test-reporter-destination',
        'test-rerun-failures',
        'test-shard',
        'test-skip-pattern',
        'test-timeout',
        'title',
        'tls-cipher-list',
        'tls-keylog',
        'trace-event-categories',
        'trace-event-file-pattern',
        'trace-require-module',
        'unhandled-rejections',
        'use-largepages',
        'v8-pool-size',
        'watch-kill-signal',
        'watch-path',
    ],
    alias: { conditions: ['C'], eval: ['e'], print: ['p'] },
    boolean: true,
    stopEarly: true,
    args: (args) => args.filter(arg => !/--test-reporter[= ](spec|tap|dot|junit|lcov)/.test(arg)),
};
const plugin = {
    title,
    isEnabled,
    entry,
    resolve,
    args,
    registerVisitors,
};
export default plugin;
