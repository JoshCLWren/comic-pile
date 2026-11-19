import type { Word } from 'unbash';
import { type ParsedArgs } from '../util/parse-args.ts';
import type { BinaryResolverOptions, GetInputsFromScriptsOptions, ScriptArg } from '../types/config.ts';
import { type Input } from '../util/input.ts';
export declare const toCommandBinary: (binary: string, { optionalBinaries }: GetInputsFromScriptsOptions, inputOptions?: {
    dir?: string;
}) => Input;
export declare const npmBooleanFlags: string[];
export declare const npmBooleanAliases: {
    force: string;
    global: string;
    'include-workspace-root': string;
    quiet: string;
    silent: string;
    workspaces: string;
    yes: string;
};
export declare const nodeLoadersArgs: {
    import: string[];
};
export declare const isGlobLike: (value: string) => boolean;
export declare const argsFrom: <T extends string | Word>(args: readonly T[], from: string) => T[];
export declare const spawningArgs: (parsed: ParsedArgs, args: string[]) => string[];
export declare const argsAfter: <T extends string | Word>(args: readonly T[], token: string) => T[];
export declare const toWordArgs: (values: (string | number)[], words: Word[]) => ScriptArg[];
export declare const expandScript: (name: string, forwardedArgs: ScriptArg[], scripts: Record<string, string> | undefined, options: BinaryResolverOptions, opts?: Partial<GetInputsFromScriptsOptions>) => Input[] | undefined;
export declare const parseNodeArgs: (args: string[]) => ParsedArgs;
