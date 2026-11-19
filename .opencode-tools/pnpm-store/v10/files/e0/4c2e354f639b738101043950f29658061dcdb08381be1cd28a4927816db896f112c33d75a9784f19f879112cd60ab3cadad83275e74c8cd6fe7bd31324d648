import type { ArrayExpression, CallExpression, Expression, ImportExpression, VariableDeclarator } from 'oxc-parser';
import type { WalkState } from './walk.ts';
export declare function markNamespaceRef(name: string, pos: number, s: WalkState, isStaticIncluded?: boolean): void;
export declare function getPromiseAllElements(expression: Expression): ArrayExpression['elements'] | undefined;
export declare function handleVariableDeclarator(node: VariableDeclarator, isVar: boolean, s: WalkState): void;
export declare function handleImportThen(node: CallExpression, s: WalkState): void;
export declare function handleImportExpression(node: ImportExpression, s: WalkState): void;
