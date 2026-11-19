import { DEFAULT_EXTENSIONS } from '../constants.js';
import { PackagePeeker } from '../PackagePeeker.js';
import { isFile } from '../util/fs.js';
import { getPackageNameFromModuleSpecifier, sanitizeSpecifier } from '../util/modules.js';
import { getEntriesFromExports, getExportEntries, getPackageTargetPaths } from '../util/package-json.js';
import { extname, join } from '../util/path.js';
export class SubpathReferences {
    chief;
    principal;
    workspaces;
    findWorkspacePackageTarget;
    isGitIgnored;
    extensions = [];
    isActive = false;
    inputs = new Map();
    seen = new Set();
    referenced = new Map();
    constructor({ chief, principal, workspaces, findWorkspacePackageTarget, isGitIgnored }) {
        this.chief = chief;
        this.principal = principal;
        this.workspaces = workspaces;
        this.findWorkspacePackageTarget = findWorkspacePackageTarget;
        this.isGitIgnored = isGitIgnored;
    }
    isSubpathSpecifier(specifier) {
        if (specifier.startsWith('#'))
            return true;
        const packageName = getPackageNameFromModuleSpecifier(specifier);
        return packageName !== undefined && this.chief.isWorkspacePackageName(packageName);
    }
    addInput(input, owner) {
        const { specifier, containingFilePath, dir } = input;
        if (!containingFilePath || !this.isSubpathSpecifier(specifier))
            return;
        const filePath = dir ? join(dir, 'package.json') : containingFilePath;
        const references = this.inputs.get(owner);
        if (references)
            references.push([specifier, filePath]);
        else
            this.inputs.set(owner, [[specifier, filePath]]);
        if (this.isActive)
            this.add(specifier, filePath);
    }
    add(specifier, containingFilePath, importedFilePath) {
        const workspace = this.chief.findWorkspaceByFilePath(containingFilePath);
        const id = `${workspace?.name ?? ''}\0${specifier}\0${importedFilePath ?? ''}`;
        if (this.seen.has(id))
            return;
        this.seen.add(id);
        const target = this.findWorkspacePackageTarget(sanitizeSpecifier(specifier), containingFilePath);
        if (!target)
            return;
        const subpaths = this.referenced.get(target.name);
        if (subpaths)
            subpaths.add(target.subpath);
        else
            this.referenced.set(target.name, new Set([target.subpath]));
        const skipFilePath = target.patternMatch === undefined ? undefined : importedFilePath;
        for (const targetPath of getPackageTargetPaths(target.target, target.dir, target.patternMatch, true)) {
            const filePath = this.principal.toSourceFilePath(targetPath, this.extensions) ?? (isFile(targetPath) ? targetPath : undefined);
            if (filePath && filePath !== skipFilePath && !this.isGitIgnored(filePath))
                this.principal.claimEntryPath(filePath);
        }
    }
    release(owner) {
        this.inputs.delete(owner);
    }
    reset() {
        this.isActive = true;
        this.extensions = [...DEFAULT_EXTENSIONS, ...this.principal.compilers.keys()];
        this.seen.clear();
        this.referenced.clear();
        this.principal.releaseEntryClaims();
        for (const references of this.inputs.values()) {
            for (const [specifier, containingFilePath] of references)
                this.add(specifier, containingFilePath);
        }
    }
    getIssues() {
        const issues = [];
        for (const { name, manifestPath, manifestStr, config } of this.workspaces) {
            const manifest = this.chief.getManifestForWorkspace(name);
            if (!manifest)
                continue;
            const referenced = this.referenced.get(name);
            const peeker = new PackagePeeker(manifestStr);
            const addIssue = (section, key) => {
                issues.push({
                    type: 'subpaths',
                    filePath: manifestPath,
                    workspace: name,
                    symbol: key,
                    ...(peeker.getPropertyLocation(section, key) ?? peeker.getPropertyLocation(section)),
                    fixes: [],
                });
            };
            if (manifest.imports) {
                for (const key in manifest.imports) {
                    if (key.startsWith('#') && manifest.imports[key] !== null && !referenced?.has(key))
                        addIssue('imports', key);
                }
            }
            if (manifest.exports && config.isIncludeSubpathExports) {
                for (const [key, value] of getExportEntries(manifest.exports)) {
                    if (value !== null && !referenced?.has(key) && this.hasModuleTarget(value))
                        addIssue('exports', key);
                }
            }
        }
        return issues;
    }
    hasModuleTarget(value) {
        return getEntriesFromExports(value).some(target => !extname(target) || this.principal.hasAcceptedExtension(target));
    }
}
