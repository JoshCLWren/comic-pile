import type { Compilers } from '../compilers/types.ts';
interface SourceFileManagerOptions {
    compilers: Compilers;
    isSession?: boolean;
}
export declare class SourceFileManager {
    sourceTextCache: Map<string, string | Promise<string>>;
    compilers: Compilers;
    private rawContentHashes;
    private isSession;
    constructor({ compilers, isSession }: SourceFileManagerOptions);
    loadSourceText(filePath: string): string | Promise<string>;
    invalidate(filePath: string): void;
    hasChanged(filePath: string): boolean;
    readRawFile(filePath: string): string | undefined;
    private cacheSourceText;
    private validateCompilerResult;
}
export {};
