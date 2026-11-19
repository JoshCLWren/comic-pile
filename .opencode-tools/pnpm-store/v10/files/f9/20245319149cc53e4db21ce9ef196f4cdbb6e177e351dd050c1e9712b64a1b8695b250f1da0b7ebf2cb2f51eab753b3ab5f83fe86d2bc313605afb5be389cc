import { promises, existsSync, readFileSync } from 'node:fs';
import { promisify } from 'node:util';
import { gzip, constants } from 'node:zlib';
import { stringify } from 'flatted';
import { resolve, relative, dirname } from 'pathe';
import c from 'tinyrainbow';
import { builtinModules } from 'node:module';
import { d as distClientRoot } from './paths-DmDZ0-yr.js';
import 'node:url';

function getTestFileEnvironment(project, testFile, browser = false) {
	if (browser) {
		return project.vite.environments.client;
	} else {
		for (const name in project.vite.environments) {
			const env = project.vite.environments[name];
			if (env.moduleGraph.getModuleById(testFile)) {
				return env;
			}
		}
	}
}

// copied from vite
// https://github.com/vitejs/vite/blob/814120f2ad387ca3d1e16c7dd403b04ca4b97f75/packages/vite/src/node/utils.ts#L106
// Supported by Node, Deno, Bun
const NODE_BUILTIN_NAMESPACE = "node:";
// Supported by Deno
const NPM_BUILTIN_NAMESPACE = "npm:";
// Supported by Bun
const BUN_BUILTIN_NAMESPACE = "bun:";
// Some runtimes like Bun injects namespaced modules here, which is not a node builtin
const nodeBuiltins = builtinModules.filter((id) => !id.includes(":"));
const { bun: isBun, deno: isDeno } = process.versions;
// TODO: Use `isBuiltin` from `node:module`, but Deno doesn't support it
function isBuiltin(id) {
	if (isDeno && id.startsWith(NPM_BUILTIN_NAMESPACE)) {
		return true;
	}
	if (isBun && id.startsWith(BUN_BUILTIN_NAMESPACE)) {
		return true;
	}
	return isNodeBuiltin(id);
}
function isNodeBuiltin(id) {
	if (id.startsWith(NODE_BUILTIN_NAMESPACE)) {
		return true;
	}
	return nodeBuiltins.includes(id);
}

function getSharedModuleGraphByProject(testModules) {
	const testModulesByProject = new Map();
	for (const testModule of testModules) {
		const projectTestModules = testModulesByProject.get(testModule.project) ?? [];
		projectTestModules.push(testModule);
		testModulesByProject.set(testModule.project, projectTestModules);
	}
	const result = {};
	for (const [project, projectTestModules] of testModulesByProject) {
		result[project.name] = getSharedModuleGraphByEnvironment(project, projectTestModules);
	}
	return result;
}
function getSharedModuleGraphByEnvironment(project, testModules) {
	const collectors = {};
	for (const testModule of testModules) {
		const environment = findModuleGraphEnvironment(project, testModule.moduleId, testModule.viteEnvironment?.name);
		// test files that never ran (e.g. cancelled by bail) have no module graph
		if (!environment) {
			continue;
		}
		collectors[environment.name] ??= createModuleGraphCollector(project, environment);
		collectors[environment.name].add(testModule.moduleId);
	}
	return Object.fromEntries(Object.entries(collectors).map(([environmentName, collector]) => [environmentName, collector.data]));
}
function findModuleGraphEnvironment(project, testFilePath, viteEnvironment) {
	if (viteEnvironment) {
		return project.vite.environments[viteEnvironment];
	}
	return project.config.experimental.viteModuleRunner === false ? project.vite.environments.__vitest__ : getTestFileEnvironment(project, testFilePath, project.config.browser.enabled);
}
function createModuleGraphCollector(project, environment) {
	const data = {
		modules: {},
		rootsByTestFile: {}
	};
	const browser = project.config.browser.enabled;
	const seen = new Map();
	function addExternal(id) {
		data.modules[id] ??= {
			external: true,
			imports: []
		};
		return id;
	}
	function get(mod) {
		if (!mod || !mod.id) {
			return;
		}
		if (mod.id === "\0vitest/browser" || mod.id.includes("plugin-vue:export-helper")) {
			return;
		}
		if (seen.has(mod)) {
			return seen.get(mod);
		}
		const id = clearId(mod.id);
		seen.set(mod, id);
		if (id.startsWith("__vite-browser-external:")) {
			return addExternal(id.slice("__vite-browser-external:".length));
		}
		if (isBuiltin(id)) {
			return addExternal(id);
		}
		const external = project._resolver.wasExternalized(id);
		if (typeof external === "string") {
			return addExternal(external);
		}
		if (browser && mod.file?.includes(project.browser.vite.config.cacheDir)) {
			return addExternal(id);
		}
		data.modules[id] = {
			external: false,
			imports: []
		};
		data.modules[id].imports = Array.from(mod.importedModules).filter((i) => i.id && !i.id.includes("/vitest/dist/")).map((m) => get(m)).filter((id) => id != null);
		return id;
	}
	// graph roots of the test file including setup files
	function add(testFilePath) {
		const roots = [testFilePath, ...project.config.setupFiles].map((file) => get(environment.moduleGraph.getModuleById(file))).filter((id) => id != null);
		data.rootsByTestFile[testFilePath] = roots;
		return roots;
	}
	return {
		data,
		add
	};
}
function clearId(id) {
	return id?.replace(/\?v=\w+$/, "") || "";
}

const gzipAsync = promisify(gzip);
class HTMLReporter {
	ctx;
	options;
	reporterDir;
	constructor(options) {
		this.options = options;
	}
	async onInit(ctx) {
		this.ctx = ctx;
		this.reporterDir = resolve(this.ctx.config.root, this.options.outputDir || ".vitest");
	}
	async onTestRunEnd(testModules, unhandledErrors) {
		const result = await serializeReportMetadata(this.ctx, testModules, unhandledErrors);
		if (this.options.singleFile) {
			await inlineAttachments(result.files);
		}
		const rawData = stringify(result);
		const data = await gzipAsync(rawData, { level: constants.Z_BEST_COMPRESSION });
		await promises.mkdir(this.reporterDir, { recursive: true });
		if (this.options.singleFile) {
			// write a single self-contained `<outputDir>/index.html`
			await handleIndexHtml({
				srcDir: distClientRoot,
				dstDir: this.reporterDir,
				data,
				singleFile: true
			});
		} else {
			// copy ui assets into `<outputDir>/ui`
			const uiDir = resolve(this.reporterDir, "ui");
			await promises.rm(uiDir, {
				recursive: true,
				force: true
			});
			await promises.cp(distClientRoot, uiDir, { recursive: true });
			// no need of ui/index.html
			await promises.rm(resolve(uiDir, "index.html"), { force: true });
			// create `<outputDir>/index.html` and `<outputDir>/ui/html.meta.json.gz`
			await handleIndexHtml({
				srcDir: distClientRoot,
				dstDir: this.reporterDir,
				data,
				singleFile: false
			});
			// copy attachments into `<outputDir>/attachments` if needed.
			// the default location matches so no extra copy.
			const attachmentsDir = this.ctx.config.attachmentsDir;
			const destAttachmentsDir = resolve(this.reporterDir, "attachments");
			if (existsSync(attachmentsDir) && attachmentsDir !== destAttachmentsDir) {
				await promises.rm(destAttachmentsDir, {
					recursive: true,
					force: true
				});
				await promises.mkdir(destAttachmentsDir, { recursive: true });
				await promises.cp(attachmentsDir, destAttachmentsDir, { recursive: true });
			}
		}
		this.ctx.logger.log(`${c.bold(c.inverse(c.magenta(" HTML ")))} ${c.magenta("Report is generated")}`);
		this.ctx.logger.log(`${c.dim("       You can run ")}${c.bold(`npx vite preview --outDir ${relative(this.ctx.config.root, this.reporterDir)}`)}${c.dim(" to see the test results.")}`);
	}
	async onFinishedReportCoverage() {
		if (this.ctx.config.coverage.enabled && this.ctx.config.coverage.htmlDir) {
			const coverageHtmlDir = this.ctx.config.coverage.htmlDir;
			const destCoverageDir = resolve(this.reporterDir, "coverage");
			if (coverageHtmlDir === destCoverageDir) {
				// skip and preserve already generated coverage report.
				// this can happen when the report `outputDir` resolves next to
				// `coverage.reportsDirectory` (e.g. default `.vitest/coverage`).
				return;
			}
			await promises.rm(destCoverageDir, {
				recursive: true,
				force: true
			});
			await promises.mkdir(destCoverageDir, { recursive: true });
			await promises.cp(coverageHtmlDir, destCoverageDir, { recursive: true });
		}
	}
}
async function serializeReportMetadata(ctx, testModules, unhandledErrors) {
	const result = {
		files: [],
		config: ctx.serializedRootConfig,
		unhandledErrors: [...unhandledErrors],
		moduleGraph: getSharedModuleGraphByProject(testModules),
		testModules: [],
		sourceCode: {
			codeTable: [],
			testModules: {}
		}
	};
	// dedupe based on project relative paths since
	// they can have different absolute paths for different test runs
	// when merging with platform blob labels and shards.
	// Source code is stored in a separate table so the same file included
	// in multiple projects can share the content while keeping distinct
	// project-relative test module entries.
	const testModuleCodes = result.sourceCode.testModules;
	const codeIndexes = new Map();
	function getCodeIndex(code) {
		const existing = codeIndexes.get(code);
		if (existing != null) {
			return existing;
		}
		const index = result.sourceCode.codeTable.length;
		codeIndexes.set(code, index);
		result.sourceCode.codeTable.push(code);
		return index;
	}
	for (const testModule of testModules) {
		result.files.push(testModule.task);
		const project = testModule.project;
		const projectName = project.name;
		result.testModules.push({
			projectName,
			moduleId: testModule.moduleId,
			relativeModuleId: testModule.relativeModuleId
		});
		testModuleCodes[projectName] ??= {};
		if (testModuleCodes[projectName][testModule.relativeModuleId] == null) {
			try {
				const code = readFileSync(testModule.moduleId, "utf-8");
				testModuleCodes[projectName][testModule.relativeModuleId] = getCodeIndex(code);
			} catch {}
		}
	}
	return result;
}
async function handleIndexHtml(options) {
	const indexHtmlFilePath = resolve(options.srcDir, "index.html");
	let html = await promises.readFile(indexHtmlFilePath, "utf-8");
	let metadataCode;
	if (options.singleFile) {
		html = await inlineHtmlAssets(indexHtmlFilePath, html);
		const base64 = options.data.toString("base64");
		metadataCode = `Promise.resolve((${uint8ArrayFromBase64.toString()})("${base64}"))`;
	} else {
		const dataFile = "html.meta.json.gz";
		await promises.writeFile(resolve(options.dstDir, "ui", dataFile), options.data);
		metadataCode = `fetch(new URL("./ui/${dataFile}", window.location.href)).then(async res => new Uint8Array(await res.arrayBuffer()))`;
		// rewrite the asset path from `./*` to `./ui/*`
		html = html.replace(/\b(href|src)="\.\//g, "$1=\"./ui/");
	}
	await promises.writeFile(resolve(options.dstDir, "index.html"), html.replace("<!-- !LOAD_METADATA! -->", `<script>window.HTML_REPORT_METADATA=${metadataCode}<\/script>`));
}
async function inlineAttachments(files) {
	for (const file of files) {
		await inlineTaskAttachments(file);
	}
}
async function inlineTaskAttachments(task) {
	if (task.type === "suite") {
		for (const child of task.tasks) {
			await inlineTaskAttachments(child);
		}
	}
	if (task.type === "test") {
		for (const annotation of task.annotations) {
			if (annotation.attachment) {
				await inlineTestAttachment(annotation.attachment);
			}
		}
		for (const artifact of task.artifacts) {
			for (const attachment of artifact.attachments ?? []) {
				await inlineTestAttachment(attachment);
			}
		}
	}
}
async function inlineTestAttachment(attachment) {
	if (attachment.path && !attachment.path.startsWith("http://") && !attachment.path.startsWith("https://")) {
		try {
			const buffer = await promises.readFile(attachment.path);
			attachment.body = buffer.toString("base64");
			attachment.bodyEncoding = "base64";
			attachment.path = undefined;
		} catch {}
	}
}
function uint8ArrayFromBase64(base64) {
	// https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Uint8Array/fromBase64
	if ("fromBase64" in Uint8Array && typeof Uint8Array.fromBase64 === "function") {
		return Uint8Array.fromBase64(base64);
	}
	function stringToUint8Array(binary) {
		const len = binary.length;
		const arr = new Uint8Array(len);
		for (let i = 0; i < len; i++) {
			arr[i] = binary.charCodeAt(i);
		}
		return arr;
	}
	return stringToUint8Array(atob(base64));
}
// regex based inlining for packages/ui/dist/client/index.html
async function inlineHtmlAssets(file, content) {
	const baseDir = dirname(file);
	content = content.replace(/<link rel="icon" href="\.\/favicon\.ico" sizes="48x48">\n/, "");
	content = content.replace(/<link rel="icon" href="(\.\/favicon\.svg)" sizes="any" type="image\/svg\+xml">/, (_, asset) => {
		const icon = readFileSync(resolve(baseDir, asset)).toString("base64");
		return `<link rel="icon" href="data:image/svg+xml;base64,${icon}" sizes="any" type="image/svg+xml">`;
	});
	content = content.replace(/<script type="module" src="(\.\/assets\/[^"]+\.js)"><\/script>/, (_, asset) => `<script type="module">${escapeInlineScript(readFileSync(resolve(baseDir, asset), "utf-8"))}<\/script>`);
	content = content.replace(/<link rel="stylesheet" href="(\.\/assets\/[^"]+\.css)">/, (_, asset) => `<style>${escapeInlineStyle(readFileSync(resolve(baseDir, asset), "utf-8"))}</style>`);
	return content;
}
function escapeInlineScript(content) {
	// https://github.com/devongovett/rsc-html-stream/blob/9b858445f4f5817470f373ae266dea04d5fcfac3/server.js#L94-L102
	return content.replace(/<!--/g, "<\\!--").replace(/<\/(script)/gi, "</\\$1");
}
function escapeInlineStyle(content) {
	return content.replace(/<\/style/gi, "<\\/style");
}

export { HTMLReporter as default };
