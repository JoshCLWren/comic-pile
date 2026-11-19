import type { Command } from 'unbash';
import type { BinaryResolverOptions, GetInputsFromScriptsOptions, ScriptArg } from '../types/config.ts';
import { type Input } from '../util/input.ts';
export declare const getInputsFromNodeOptions: (prefix: Command['prefix']) => Input[];
export declare const getDependenciesFromCommand: (node: Pick<Command, 'name' | 'prefix' | 'args'>, options: BinaryResolverOptions, fromWords?: (args: ScriptArg[], options: GetInputsFromScriptsOptions) => Input[]) => Input[];
