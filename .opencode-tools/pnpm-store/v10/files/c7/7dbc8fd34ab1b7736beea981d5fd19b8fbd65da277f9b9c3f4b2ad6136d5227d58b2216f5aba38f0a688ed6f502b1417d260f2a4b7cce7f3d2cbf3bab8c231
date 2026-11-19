import { AsyncLocalStorage } from 'node:async_hooks';
import { formatCauseMessage } from './errors.js';
import { logError } from './log.js';
import { toRelative } from './path.js';
const loading = new AsyncLocalStorage();
let loads;
let isRejected = false;
export const hasUnhandledRejection = () => isRejected;
export const trackConfigLoad = (configFilePath, cache, fn) => {
    loads?.set(configFilePath, cache);
    return loading.run(configFilePath, fn);
};
export const listenForUnhandledRejections = (getCwd) => {
    const tracked = (loads = new Map());
    process.on('unhandledRejection', reason => {
        isRejected = true;
        process.exitCode = 2;
        const cwd = getCwd();
        const likelyFrom = loading.getStore();
        const error = reason instanceof Error ? reason : new Error(String(reason));
        const origin = likelyFrom ? `, likely from ${toRelative(likelyFrom, cwd)}` : '';
        logError(`Unhandled rejection${origin} (${formatCauseMessage(error, cwd)})`);
        logError('Please fix or visit https://knip.dev/reference/known-issues');
        for (const [configFilePath, cache] of tracked)
            cache.removeEntry(configFilePath);
        for (const cache of new Set(tracked.values()))
            cache.reconcile();
    });
};
