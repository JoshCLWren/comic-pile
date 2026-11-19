import { type ArithmeticCommandExpansion, type Command, type CommandExpansionPart, type ProcessSubstitutionPart, type SyntaxNode, type Word } from 'unbash';
export declare const toShellCommand: (argv: string[]) => string;
export declare const getCommandWords: (node: Pick<Command, 'args'>) => Word[];
export declare const collectCommands: (root: SyntaxNode) => Command[];
export declare const isScriptExpansion: (node: SyntaxNode) => node is CommandExpansionPart | ProcessSubstitutionPart | ArithmeticCommandExpansion;
