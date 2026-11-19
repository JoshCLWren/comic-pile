import { IGNORED_GLOBAL_BINARIES } from '../constants.js';
import { debugLog } from './debug.js';
import { fromBinary, isConfig, isDeferResolveEntry, toDebugString } from './input.js';
import { getPackageNameFromFilePath, getPackageNameFromSpecifier } from './modules.js';
import { dirname, isAbsolute, isInNodeModules, isInternal, join } from './path.js';
import { _resolveModuleSync, _resolveSync, resolvePackageManifestPath } from './resolve.js';
const CHAR_HASH = 35;
const CHAR_AT = 64;
const CHAR_TILDE = 126;
const isJoinable = (specifier) => {
    const char = specifier.charCodeAt(0);
    return char !== CHAR_HASH && char !== CHAR_TILDE && char !== CHAR_AT && !isAbsolute(specifier);
};
export const createInputHandler = (deputy, chief, isGitIgnored, addIssue, externalRefs, options) => {
    const getWorkspaceFor = (input, containingFilePath, workspace) => (input.dir && chief.findWorkspaceByFilePath(`${input.dir}/`)) ||
        chief.findWorkspaceByFilePath(containingFilePath) ||
        workspace;
    const addExternalRef = (containingFilePath, specifier, identifier) => {
        if (!externalRefs)
            return;
        const ref = { specifier, identifier };
        const refs = externalRefs.get(containingFilePath);
        if (refs)
            refs.add(ref);
        else
            externalRefs.set(containingFilePath, new Set([ref]));
    };
    const isReportable = (input) => !input.optional && (!options.isProduction || input.production);
    const report = (type, filePath, workspace, symbol) => addIssue({ type, filePath, workspace: workspace.name, symbol, specifier: symbol, fixes: [] });
    const credit = (input, containingFilePath, workspace, packageName) => {
        const reference = {
            specifier: input.specifier,
            isDevOnly: isConfig(input),
            isTypeOnly: input.isTypeOnly,
            isDevelopment: !input.production,
        };
        const isHandled = deputy.maybeAddReferencedExternalDependency(workspace, packageName, reference);
        if (!input.alsoReferenceOwner)
            return isHandled;
        const owner = chief.findWorkspaceByFilePath(containingFilePath);
        if (!owner || owner === workspace)
            return isHandled;
        const isOwnerHandled = deputy.maybeAddReferencedExternalDependency(owner, packageName, reference);
        return isHandled || isOwnerHandled;
    };
    const resolveWorkspacePath = (specifier, containingFilePath) => {
        const filePath = _resolveSync(specifier, dirname(containingFilePath));
        if (filePath && isInternal(filePath) && !isGitIgnored(filePath))
            return filePath;
    };
    const handleFile = (input, containingFilePath, workspace, recordedPackageName) => {
        const { specifier } = input;
        const basePath = input.dir ? join(input.dir, 'file.ts') : containingFilePath;
        const filePath = isJoinable(specifier) ? join(input.dir ?? dirname(containingFilePath), specifier) : specifier;
        const resolvedFilePath = _resolveModuleSync(filePath, basePath) ??
            (filePath === specifier ? undefined : _resolveModuleSync(specifier, basePath));
        if (resolvedFilePath && isInternal(resolvedFilePath)) {
            return isGitIgnored(resolvedFilePath) ? undefined : resolvedFilePath;
        }
        const inputWorkspace = getWorkspaceFor(input, containingFilePath, workspace);
        if (resolvedFilePath || !isInternal(filePath)) {
            const packageName = resolvedFilePath
                ? getPackageNameFromFilePath(resolvedFilePath)
                : getPackageNameFromSpecifier(specifier);
            if (packageName) {
                if (packageName !== recordedPackageName && !chief.findWorkspaceByPackageName(packageName, containingFilePath)) {
                    addExternalRef(containingFilePath, packageName);
                }
                if (!credit(input, containingFilePath, inputWorkspace, packageName) && isReportable(input)) {
                    report('unlisted', containingFilePath, inputWorkspace, packageName);
                }
                return;
            }
        }
        if ((isInternal(filePath) && isGitIgnored(filePath)) || !isReportable(input))
            return;
        if (isDeferResolveEntry(input) || isConfig(input)) {
            debugLog(inputWorkspace.name, `Unable to resolve ${toDebugString(input, options.cwd)}`);
        }
        else {
            report('unresolved', containingFilePath, inputWorkspace, specifier);
        }
    };
    const handleBinary = (input, containingFilePath, workspace) => {
        const binaryName = fromBinary(input);
        const inputWorkspace = getWorkspaceFor(input, containingFilePath, workspace);
        const dependencies = deputy.maybeAddReferencedBinary(inputWorkspace, binaryName, !input.production);
        if (dependencies) {
            for (const dependency of dependencies) {
                addExternalRef(containingFilePath, dependency, binaryName);
            }
            return;
        }
        if (!isReportable(input) ||
            (inputWorkspace.config.ignoreGlobalBinaries && IGNORED_GLOBAL_BINARIES.has(binaryName))) {
            return;
        }
        report('binaries', containingFilePath, inputWorkspace, binaryName);
    };
    const handleDependency = (input, containingFilePath, workspace) => {
        const packageName = getPackageNameFromSpecifier(input.specifier);
        if (!packageName)
            return handleFile(input, containingFilePath, workspace);
        const inputWorkspace = getWorkspaceFor(input, containingFilePath, workspace);
        if (externalRefs && !chief.findWorkspaceByPackageName(packageName, containingFilePath)) {
            addExternalRef(containingFilePath, packageName);
        }
        if (credit(input, containingFilePath, inputWorkspace, packageName)) {
            return resolveWorkspacePath(input.specifier, containingFilePath);
        }
        if (isReportable(input))
            report('unlisted', containingFilePath, inputWorkspace, packageName);
    };
    const handlePackageOrFile = (input, containingFilePath, workspace) => {
        const packageName = getPackageNameFromSpecifier(input.specifier);
        if (!packageName)
            return handleFile(input, containingFilePath, workspace);
        const inputWorkspace = getWorkspaceFor(input, containingFilePath, workspace);
        const isWorkspace = chief.findWorkspaceByPackageName(packageName, containingFilePath) !== undefined;
        if (!isWorkspace)
            addExternalRef(containingFilePath, packageName);
        if (credit(input, containingFilePath, inputWorkspace, packageName)) {
            return isWorkspace ? resolveWorkspacePath(input.specifier, containingFilePath) : undefined;
        }
        if (isWorkspace || resolvePackageManifestPath(packageName, input.dir ?? dirname(containingFilePath))) {
            if (isReportable(input))
                report('unlisted', containingFilePath, inputWorkspace, packageName);
            return;
        }
        return handleFile(input, containingFilePath, workspace, packageName);
    };
    return (input, workspace) => {
        const { specifier, containingFilePath } = input;
        if (!containingFilePath)
            return;
        switch (input.type) {
            case 'binary':
                handleBinary(input, containingFilePath, workspace);
                return;
            case 'dependency':
                return handleDependency(input, containingFilePath, workspace);
            case 'deferResolve':
            case 'config':
                return handlePackageOrFile(input, containingFilePath, workspace);
            case 'deferResolveEntry':
                return isInNodeModules(specifier)
                    ? handlePackageOrFile(input, containingFilePath, workspace)
                    : handleFile(input, containingFilePath, workspace);
            case 'entry':
                return handleFile(input, containingFilePath, workspace);
        }
    };
};
