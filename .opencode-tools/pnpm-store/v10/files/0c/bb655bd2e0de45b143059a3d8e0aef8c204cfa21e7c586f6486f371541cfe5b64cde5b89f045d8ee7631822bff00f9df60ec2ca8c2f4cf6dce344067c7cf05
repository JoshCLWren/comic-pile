"use strict";
Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
const utils = require("./utils.cjs");
function classifyScrollEvent({
  offset,
  isScrolling,
  elementMax,
  holdOffset,
  scrollOffset,
  pendingWrite,
  clampedMaxAtWrite
}) {
  var _a;
  if (isScrolling && pendingWrite === null && offset === scrollOffset) {
    return "spurious";
  }
  if (pendingWrite !== null && Math.abs(offset - pendingWrite.target) < 1.5) {
    return "readBack";
  }
  if (pendingWrite !== null && !pendingWrite.smooth && elementMax !== null && pendingWrite.target > elementMax + holdOffset + 0.5 && Math.abs(offset - (elementMax + holdOffset)) < 1.5) {
    return "clampedReadBack";
  }
  if (pendingWrite !== null && !pendingWrite.smooth && ((_a = pendingWrite.lowMaxes) == null ? void 0 : _a.some((max) => Math.abs(offset - max) < 1.5))) {
    return "clampedReadBack";
  }
  if (clampedMaxAtWrite !== null && Math.abs(offset - clampedMaxAtWrite) < 1.5) {
    return "clampedEcho";
  }
  return "external";
}
const isAnimating = (phase) => phase === "smooth" || phase === "smoothFinishing";
function externalRetiresCommand({
  kind,
  offset,
  command,
  target
}) {
  return kind !== "spurious" && kind !== "readBack" && // Our own write, clamped (`clampedReadBack`, #1310): the command is not
  // retired by it, and reconcile retargets below the new max.
  kind !== "clampedReadBack" && (command == null ? void 0 : command.index) != null && // Nothing has been written for a command waiting for the tail; these
  // are the fling's events.
  command.phase !== "queued" && // A non-smooth write lands at once, so any other scroll event is the
  // user's, even before reconcile saw the target reached (the target may
  // keep moving, or iOS ignored the write under a finger). A write the
  // browser clamped because the sizer hasn't grown yet reads back at the
  // max, which is also where the fresh target clamps, so the check below
  // keeps it reconciling (#1294). While a smooth scroll's animation may
  // still report, its events look like a user's, so it yields only once it
  // has landed.
  !isAnimating(command.phase) && !utils.approxEqual(offset, command.lastTargetOffset) && !utils.approxEqual(offset, target()) && // A compensation write's clamped echo (#1258) keeps the command. The
  // order is deliberate, not tidiness: this clause stays after `target()`
  // (and `clampedReadBack` before it) because `target()` can rebuild the
  // measurements, so it must run for exactly the events it always did.
  kind !== "clampedEcho";
}
const FLING_WINDOW_MS = 40;
function flingSpedUp(samples) {
  const last = samples[samples.length - 1];
  if (last === void 0) return false;
  let j = samples.length - 2;
  while (j >= 0 && last.t - samples[j].t < FLING_WINDOW_MS) j--;
  if (j < 0) return false;
  const mid = samples[j];
  let k = j - 1;
  while (k >= 0 && mid.t - samples[k].t < FLING_WINDOW_MS) k--;
  if (k < 0) return false;
  const first = samples[k];
  const recent = (last.offset - mid.offset) / (last.t - mid.t);
  const before = (mid.offset - first.offset) / (mid.t - first.t);
  return recent * before >= 0 && Math.abs(recent) >= 2 * Math.abs(before) && Math.abs(recent) - Math.abs(before) >= 0.8;
}
function flingCaught(samples) {
  const last = samples[samples.length - 1];
  if (last === void 0) return false;
  let j = samples.length - 2;
  while (j >= 0 && last.t - samples[j].t < FLING_WINDOW_MS) j--;
  if (j < 0) return false;
  const from = samples[j];
  return Math.abs(last.offset - from.offset) / (last.t - from.t) >= 0.05;
}
exports.classifyScrollEvent = classifyScrollEvent;
exports.externalRetiresCommand = externalRetiresCommand;
exports.flingCaught = flingCaught;
exports.flingSpedUp = flingSpedUp;
//# sourceMappingURL=scroll-classifier.cjs.map
