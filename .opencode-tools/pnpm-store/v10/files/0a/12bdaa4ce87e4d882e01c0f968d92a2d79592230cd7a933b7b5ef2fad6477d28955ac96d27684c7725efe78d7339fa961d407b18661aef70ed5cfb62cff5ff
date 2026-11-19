"use strict";
Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
let _isIOSResult;
const isIOSWebKit = () => {
  if (_isIOSResult !== void 0) return _isIOSResult;
  if (typeof navigator === "undefined") return _isIOSResult = false;
  if (/iP(hone|od|ad)/.test(navigator.userAgent)) return _isIOSResult = true;
  const mtp = navigator.maxTouchPoints;
  return _isIOSResult = navigator.platform === "MacIntel" && mtp !== void 0 && mtp > 0;
};
let _iosMomentumOverridesWritesResult;
const iosMomentumOverridesWrites = () => {
  if (_iosMomentumOverridesWritesResult !== void 0) {
    return _iosMomentumOverridesWritesResult;
  }
  return _iosMomentumOverridesWritesResult = isIOSWebKit() && typeof CSS !== "undefined" && typeof CSS.supports === "function" && CSS.supports("overflow-anchor: auto");
};
const momentumOverridesWrites = () => !isIOSWebKit() || iosMomentumOverridesWrites();
const _resetIOSDetectionForTests = () => {
  _isIOSResult = void 0;
  _iosMomentumOverridesWritesResult = void 0;
};
const touchListenerOptions = {
  capture: true,
  passive: true
};
class IosGesture {
  constructor(host) {
    this.host = host;
    this._touch = null;
    this.inMotion = () => this._touch !== null && this._touch.phase !== "lateFling";
    this.dragging = () => {
      var _a;
      return ((_a = this._touch) == null ? void 0 : _a.phase) === "down" && this._touch.moved;
    };
    this.tail = () => {
      var _a;
      return ((_a = this._touch) == null ? void 0 : _a.phase) === "tail" ? this._touch.moved ? "fling" : "tap" : null;
    };
    this.onScroll = ({
      isScrolling,
      ownReadBack,
      moved,
      external
    }) => {
      var _a, _b, _c;
      if (isScrolling && ((_a = this._touch) == null ? void 0 : _a.phase) === "tail") {
        this._openTail(this._touch.moved || !ownReadBack, false);
      } else if (((_b = this._touch) == null ? void 0 : _b.phase) === "lateFling") {
        if (this.host.now() > this._touch.until) {
          this._touch = null;
        } else if (external && isScrolling && moved) {
          this._openTail(true, false);
        }
      }
      if (!ownReadBack && isScrolling && moved && ((_c = this._touch) == null ? void 0 : _c.phase) === "down") {
        this._touch.moved = true;
        return true;
      }
      return false;
    };
    this.touchStart = () => {
      this.end();
      this._touch = { phase: "down", moved: false };
    };
    this.touchEnd = () => {
      var _a;
      const moved = ((_a = this._touch) == null ? void 0 : _a.phase) === "down" && this._touch.moved;
      this.end();
      this._openTail(moved, moved);
    };
    this.end = () => {
      var _a;
      const win = this.host.getWindow();
      if (((_a = this._touch) == null ? void 0 : _a.phase) === "tail" && win != null) {
        win.clearTimeout(this._touch.timerId);
      }
      this._touch = null;
    };
    this.listen = (target) => {
      const onTouchStart = () => this.touchStart();
      const onTouchEnd = () => this.touchEnd();
      target.addEventListener("touchstart", onTouchStart, touchListenerOptions);
      target.addEventListener("touchend", onTouchEnd, touchListenerOptions);
      target.addEventListener("touchcancel", onTouchEnd, touchListenerOptions);
      return () => {
        target.removeEventListener(
          "touchstart",
          onTouchStart,
          touchListenerOptions
        );
        target.removeEventListener("touchend", onTouchEnd, touchListenerOptions);
        target.removeEventListener(
          "touchcancel",
          onTouchEnd,
          touchListenerOptions
        );
        this.end();
      };
    };
    this._openTail = (moved, awaitingFling) => {
      const win = this.host.getWindow();
      if (win == null) return;
      this.end();
      const tail = {
        phase: "tail",
        moved,
        awaitingFling,
        // Only fires while this tail is current: `end` clears it otherwise.
        timerId: win.setTimeout(() => {
          if (this.host.tailStillMoving()) {
            this._openTail(tail.moved, tail.awaitingFling);
            return;
          }
          this._touch = tail.awaitingFling ? { phase: "lateFling", until: this.host.now() + 1e3 } : null;
          this.host.onTailClosed();
        }, 150)
      };
      this._touch = tail;
    };
  }
  get touch() {
    return this._touch;
  }
}
exports.IosGesture = IosGesture;
exports._resetIOSDetectionForTests = _resetIOSDetectionForTests;
exports.iosMomentumOverridesWrites = iosMomentumOverridesWrites;
exports.isIOSWebKit = isIOSWebKit;
exports.momentumOverridesWrites = momentumOverridesWrites;
//# sourceMappingURL=ios-gesture.cjs.map
