const title = 'ts-node';
const args = {
    binaries: ['ts-node', 'ts-node-cwd', 'ts-node-esm', 'ts-node-script', 'ts-node-transpile-only'],
    positional: (parsed) => (parsed.eval === undefined ? parsed._.slice(0, 1) : []),
    nodeImportArgs: true,
    string: [
        'compiler',
        'compilerOptions',
        'cwd',
        'dir',
        'eval',
        'experimentalSpecifierResolution',
        'ignore',
        'ignoreDiagnostics',
        'project',
        'scopeDir',
        'transpiler',
    ],
    alias: {
        compiler: ['C'],
        compilerOptions: ['O', 'compiler-options'],
        eval: ['e'],
        ignore: ['I'],
        ignoreDiagnostics: ['D', 'ignore-diagnostics'],
        project: ['P'],
    },
    boolean: true,
    stopEarly: true,
};
const plugin = {
    title,
    args,
};
export default plugin;
