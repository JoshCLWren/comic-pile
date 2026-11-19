type Cache = {
    removeEntry: (filePath: string) => void;
    reconcile: () => void;
};
export declare const hasUnhandledRejection: () => boolean;
export declare const trackConfigLoad: <T>(configFilePath: string, cache: Cache, fn: () => Promise<T>) => Promise<T>;
export declare const listenForUnhandledRejections: (getCwd: () => string) => void;
export {};
