import { execFile, spawn } from "node:child_process";
import * as fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import {
  resolvePackageCommand,
  runPackageFormatterTextCommand
} from "./runFormatterCommand.js";
const editorServiceSchemaVersion = 5;
const messageKinds = {
  canFormat: 4,
  canFormatResponse: 5,
  error: 1,
  formatFile: 6,
  formatFileResponse: 7
};
const successBytes = Buffer.from([255, 255, 255, 255]);
const editorServices = /* @__PURE__ */ new Map();
function encodeMessage(id, kind, body) {
  return Buffer.concat([
    encodeU32(id),
    encodeU32(kind),
    encodeU32(body.length),
    body,
    successBytes
  ]);
}
function encodeString(value) {
  const buffer = Buffer.from(value);
  return Buffer.concat([encodeU32(buffer.length), buffer]);
}
function encodeU32(value) {
  const buffer = Buffer.alloc(4);
  buffer.writeUInt32BE(value);
  return buffer;
}
async function getEditorService(cwd) {
  let editorService = editorServices.get(cwd);
  if (!editorService) {
    editorService = startEditorService(cwd);
    editorServices.set(cwd, editorService);
  }
  return await editorService;
}
async function startEditorService(cwd) {
  const info = await resolvePackageCommand(
    { command: "dprint" },
    ["editor-info"],
    cwd
  );
  try {
    const { stdout } = await promisify(execFile)(info.command, info.args, {
      cwd
    });
    const { schemaVersion } = JSON.parse(stdout);
    if (schemaVersion !== editorServiceSchemaVersion) {
      return void 0;
    }
  } catch {
    return void 0;
  }
  const { args, command } = await resolvePackageCommand(
    { command: "dprint" },
    ["editor-service", "--parent-pid", String(process.pid)],
    cwd
  );
  const child = spawn(command, args, {
    cwd,
    stdio: ["pipe", "pipe", "ignore"]
  });
  const pending = /* @__PURE__ */ new Map();
  let buffer = Buffer.alloc(0);
  let nextId = 0;
  function updateRef() {
    for (const handle of [child, child.stdin, child.stdout]) {
      if (pending.size) {
        handle.ref();
      } else {
        handle.unref();
      }
    }
  }
  function stop(error) {
    editorServices.delete(cwd);
    for (const { reject } of pending.values()) {
      reject(error);
    }
    pending.clear();
  }
  function handleMessage(kind, body) {
    if (kind !== messageKinds.canFormatResponse && kind !== messageKinds.error && kind !== messageKinds.formatFileResponse) {
      return;
    }
    const requestId = body.readUInt32BE(0);
    const request2 = pending.get(requestId);
    if (!request2) {
      return;
    }
    pending.delete(requestId);
    updateRef();
    request2.resolve({ body, kind });
  }
  async function request(kind, body) {
    return await new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { reject, resolve });
      updateRef();
      child.stdin.write(encodeMessage(id, kind, body));
    });
  }
  child.on("error", stop);
  child.on("exit", (code) => {
    stop(new Error(`dprint editor-service exited with code ${String(code)}.`));
  });
  child.stdin.on("error", () => void 0);
  child.stdout.on("data", (data) => {
    buffer = Buffer.concat([buffer, data]);
    while (buffer.length >= 12) {
      const bodyLength = buffer.readUInt32BE(8);
      const messageLength = 12 + bodyLength + successBytes.length;
      if (buffer.length < messageLength) {
        return;
      }
      handleMessage(
        buffer.readUInt32BE(4),
        buffer.subarray(12, 12 + bodyLength)
      );
      buffer = buffer.subarray(messageLength);
    }
  });
  updateRef();
  const realCwd = await fs.realpath(cwd).catch(() => path.resolve(cwd));
  return async ({ filePath: rawFilePath, text }) => {
    const filePath = path.join(realCwd, path.relative(cwd, rawFilePath));
    const canFormat = await request(
      messageKinds.canFormat,
      encodeString(filePath)
    );
    if (!canFormat.body.readUInt32BE(4)) {
      return { formatted: text };
    }
    const textBuffer = Buffer.from(text);
    const response = await request(
      messageKinds.formatFile,
      Buffer.concat([
        encodeString(filePath),
        encodeU32(0),
        encodeU32(textBuffer.length),
        encodeString(""),
        encodeString(textBuffer)
      ])
    );
    if (response.kind === messageKinds.error) {
      return { error: new Error(response.body.subarray(8).toString()) };
    }
    return {
      formatted: response.body.readUInt32BE(4) ? response.body.subarray(12).toString() : text
    };
  };
}
const formatTextDprint = async (options) => {
  const editorService = await getEditorService(options.cwd);
  if (editorService) {
    try {
      return await editorService(options);
    } catch (error) {
      return { error };
    }
  }
  return await runPackageFormatterTextCommand(
    {
      args: (filePath) => ["fmt", "--stdin", filePath],
      command: "dprint"
    },
    options
  );
};
export {
  formatTextDprint
};
