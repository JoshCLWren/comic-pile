import type { ConfigurationChief, Workspace } from '../ConfigurationChief.ts';
import type { ProjectPrincipal } from '../ProjectPrincipal.ts';
import type { Issue } from '../types/issues.ts';
import type { Input } from '../util/input.ts';
import type { WorkspacePackageTargetHandler } from '../util/to-source-path.ts';
interface SubpathReferencesOptions {
    chief: ConfigurationChief;
    principal: ProjectPrincipal;
    workspaces: Workspace[];
    findWorkspacePackageTarget: WorkspacePackageTargetHandler;
    isGitIgnored: (filePath: string) => boolean;
}
export declare class SubpathReferences {
    private chief;
    private principal;
    private workspaces;
    private findWorkspacePackageTarget;
    private isGitIgnored;
    private extensions;
    private isActive;
    private inputs;
    private seen;
    private referenced;
    constructor({ chief, principal, workspaces, findWorkspacePackageTarget, isGitIgnored }: SubpathReferencesOptions);
    private isSubpathSpecifier;
    addInput(input: Input, owner: string): void;
    add(specifier: string, containingFilePath: string, importedFilePath?: string): void;
    release(owner: string): void;
    reset(): void;
    getIssues(): Issue[];
    private hasModuleTarget;
}
export {};
