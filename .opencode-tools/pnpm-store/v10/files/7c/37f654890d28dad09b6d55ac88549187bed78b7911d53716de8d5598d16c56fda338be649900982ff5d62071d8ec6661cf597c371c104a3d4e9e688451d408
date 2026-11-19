import type { Word } from 'unbash';
type ParsedValue = any;
export interface ParsedArgs {
    _: string[];
    '--'?: string[];
    positionalIndices?: number[];
    [key: string]: ParsedValue;
}
interface Opts {
    isStorePositions?: boolean;
    string?: string[];
    boolean?: string[] | true;
    alias?: Record<string, string | string[]>;
    '--'?: boolean;
    stopEarly?: boolean;
}
declare const parseArgs: (input: readonly (string | Word)[], opts?: Opts) => ParsedArgs;
export default parseArgs;
