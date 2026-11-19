import { readFile } from 'node:fs/promises';
import { ROOT_WORKSPACE_NAME } from './constants.js';
import { JsonCatalogPeeker } from './JsonCatalogPeeker.js';
import { PackagePeeker } from './PackagePeeker.js';
import { extractCatalogReferences, getOverrideCatalogReferences, parseCatalog, } from './util/catalog.js';
import { extname } from './util/path.js';
import { YamlCatalogPeeker } from './YamlCatalogPeeker.js';
export class CatalogCounselor {
    sources = [];
    entries = new Set();
    referencedEntries = new Set();
    referenceIssues = [];
    constructor(options) {
        for (const container of options.catalog) {
            const entries = parseCatalog(container);
            const overrideReferences = getOverrideCatalogReferences(container.overrides);
            for (const entry of entries)
                this.entries.add(entry);
            for (const reference of overrideReferences)
                this.addReference(reference);
            this.sources.push({ filePath: container.filePath, entries, overrideReferences });
        }
    }
    addReferencedCatalogEntry(entryName) {
        this.referencedEntries.add(entryName);
    }
    addReference({ catalogName, packageName }) {
        this.addReferencedCatalogEntry(`${catalogName}:${packageName}`);
    }
    addWorkspace({ name: workspace, manifest, manifestPath: filePath, manifestStr, }) {
        const catalogReferences = extractCatalogReferences(manifest);
        if (workspace === ROOT_WORKSPACE_NAME) {
            for (const reference of getOverrideCatalogReferences(manifest.pnpm?.overrides))
                catalogReferences.push(reference);
        }
        if (catalogReferences.length === 0)
            return;
        const peeker = new PackagePeeker(manifestStr);
        for (const { catalogName, packageName, selector } of catalogReferences) {
            const catalogEntryName = `${catalogName}:${packageName}`;
            this.addReferencedCatalogEntry(catalogEntryName);
            if (!this.entries.has(catalogEntryName)) {
                const pos = peeker.getCatalogReferenceLocation(selector ?? packageName, catalogName);
                this.referenceIssues.push({
                    type: 'catalogReferences',
                    filePath,
                    workspace,
                    symbol: packageName,
                    parentSymbol: catalogName,
                    fixes: [],
                    ...pos,
                });
            }
        }
    }
    async settleCatalogIssues(options) {
        const workspace = ROOT_WORKSPACE_NAME;
        const catalogIssues = [];
        const overrideReferenceIssues = [];
        for (const { filePath, entries, overrideReferences } of this.sources) {
            if (entries.size === 0 && overrideReferences.length === 0)
                continue;
            const fileContent = await readFile(filePath, 'utf-8');
            const isYaml = ['.yml', '.yaml'].includes(extname(filePath));
            const yamlPeeker = isYaml ? new YamlCatalogPeeker(fileContent) : undefined;
            const peeker = yamlPeeker ?? new JsonCatalogPeeker(fileContent);
            for (const entry of entries) {
                if (!this.referencedEntries.has(entry)) {
                    const [parentSymbol, symbol] = entry.split(':');
                    const pos = peeker.getLocation(parentSymbol, symbol);
                    const fixes = [];
                    if (options.isFix && isYaml && pos)
                        fixes.push([pos.line, 0, 0]);
                    catalogIssues.push({ type: 'catalog', filePath, workspace, symbol, parentSymbol, fixes, ...pos });
                }
            }
            for (const { catalogName, packageName, selector } of overrideReferences) {
                if (this.entries.has(`${catalogName}:${packageName}`))
                    continue;
                const pos = yamlPeeker?.getOverrideCatalogReferenceLocation(selector);
                overrideReferenceIssues.push({
                    type: 'catalogReferences',
                    filePath,
                    workspace,
                    symbol: packageName,
                    parentSymbol: catalogName,
                    fixes: [],
                    ...pos,
                });
            }
        }
        return [...catalogIssues, ...this.referenceIssues, ...overrideReferenceIssues];
    }
}
