// This file loads the anti-slop plugin via jiti
const jiti = require("jiti");
const j = jiti(__filename);
module.exports = j("./index.ts");
