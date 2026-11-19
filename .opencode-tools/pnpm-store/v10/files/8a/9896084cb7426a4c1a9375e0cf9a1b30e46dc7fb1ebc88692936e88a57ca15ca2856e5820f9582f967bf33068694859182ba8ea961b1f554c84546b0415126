import { forEachChild, } from 'unbash';
export const toShellCommand = (argv) => argv.map(arg => `'${arg.replaceAll("'", `'\\''`)}'`).join(' ');
export const getCommandWords = (node) => node.args.filter((arg) => arg.type === 'Word');
export const collectCommands = (root) => {
    const commands = [];
    const visit = (node) => {
        if (node.type === 'Command')
            commands.push(node);
        if (!isScriptExpansion(node))
            forEachChild(node, visit);
    };
    visit(root);
    return commands;
};
export const isScriptExpansion = (node) => node.type === 'CommandExpansion' || node.type === 'ProcessSubstitution' || node.type === 'ArithmeticCommandExpansion';
