import LESS from './less.js';
import MDX from './mdx.js';
import SCSS from './scss.js';
import STYLUS from './stylus.js';
import TSRX from './tsrx.js';
export const normalizeCompilerExtension = (ext) => ext.replace(/^\.*/, '.');
export const normalizeCompilers = (rawLocalConfig) => {
    const compilers = new Map();
    for (const extension in rawLocalConfig.compilers) {
        const ext = normalizeCompilerExtension(extension);
        const compilerFn = rawLocalConfig.compilers[extension];
        if (typeof compilerFn === 'function' || compilerFn === true)
            compilers.set(ext, compilerFn);
    }
    for (const extension in rawLocalConfig.asyncCompilers) {
        const ext = normalizeCompilerExtension(extension);
        compilers.set(ext, rawLocalConfig.asyncCompilers[extension]);
    }
    return compilers;
};
export const builtInCompilers = [
    { extensions: ['.mdx'], ...MDX },
    { extensions: ['.sass', '.scss'], ...SCSS },
    { extensions: ['.less'], ...LESS },
    { extensions: ['.styl', '.stylus'], ...STYLUS },
    { extensions: ['.tsrx'], ...TSRX },
];
export const getIncludedCompilers = (rawCompilers, dependencies, onReferencedDependency) => {
    const compilers = new Map();
    for (const [extension, compiler] of rawCompilers) {
        if (typeof compiler === 'function')
            compilers.set(extension, compiler);
    }
    for (const { extensions, dependencies: compilerDependencies, compiler } of builtInCompilers) {
        let hasCompilerDependency = false;
        for (const dependency of compilerDependencies) {
            if (dependencies.has(dependency)) {
                hasCompilerDependency = true;
                if (onReferencedDependency)
                    onReferencedDependency(dependency);
                else
                    break;
            }
        }
        for (const extension of extensions) {
            const existingCompiler = rawCompilers.get(extension);
            if (existingCompiler === true || (existingCompiler === undefined && hasCompilerDependency)) {
                compilers.set(extension, compiler);
            }
        }
    }
    return compilers;
};
