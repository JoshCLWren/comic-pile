import type { ParsedArgs } from '../util/parse-args.ts';
import type { Input } from '../util/input.ts';
import type { Manifest } from '../util/package-json.ts';
export type ConfigArg = boolean | (string | [string, (id: string) => string])[];
export type Args = {
    binaries?: string[];
    positional?: boolean | ((parsed: ParsedArgs) => string[]);
    string?: string[];
    boolean?: string[] | true;
    stopEarly?: boolean;
    alias?: Record<string, string[]>;
    resolve?: string[];
    nodeImportArgs?: boolean;
    config?: ConfigArg;
    args?: (args: string[]) => string[];
    fromArgs?: string[] | ((parsed: ParsedArgs, args: string[], options: {
        cwd: string;
    }) => string[] | string);
    resolveInputs?: (parsed: ParsedArgs, options: {
        cwd: string;
        args: string[];
        manifest: Manifest;
    }) => Input[];
};
