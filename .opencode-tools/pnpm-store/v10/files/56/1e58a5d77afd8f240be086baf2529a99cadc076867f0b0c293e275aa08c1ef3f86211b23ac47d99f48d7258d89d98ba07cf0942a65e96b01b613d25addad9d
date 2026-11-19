import { fileURLToPath } from "node:url";
// src/reactCompilerBabelPreset.ts
function reactCompilerBabelPreset(_api, options = {}) {
	return { plugins: [[fileURLToPath(import.meta.resolve("babel-plugin-react-compiler")), options]] };
}
export { reactCompilerBabelPreset as default };
