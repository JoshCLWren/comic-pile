"use strict";

const conversions = require("webidl-conversions");
const utils = require("./utils.js");

const PointerEvent = require("./PointerEvent.js");
const MouseEventInit = require("./MouseEventInit.js");

exports._convertInherit = (globalObject, obj, ret, { context = "The provided value" } = {}) => {
  MouseEventInit._convertInherit(globalObject, obj, ret, { context });

  {
    const key = "altitudeAngle";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["double"](value, {
        context: `${context}'s 'altitudeAngle' member`,
        globals: globalObject,
      });

      ret[key] = value;
    }
  }

  {
    const key = "azimuthAngle";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["double"](value, {
        context: `${context}'s 'azimuthAngle' member`,
        globals: globalObject,
      });

      ret[key] = value;
    }
  }

  {
    const key = "coalescedEvents";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      if (!utils.isObject(value)) {
        throw new globalObject.TypeError(
          `${context}'s 'coalescedEvents' member is not an iterable object.`,
        );
      } else {
        const V = [];
        const tmp = value;
        for (let nextItem of tmp) {
          nextItem = PointerEvent.convert(globalObject, nextItem, {
            context: `${context}'s 'coalescedEvents' member's element`,
          });

          V.push(nextItem);
        }
        value = V;
      }

      ret[key] = value;
    } else {
      ret[key] = [];
    }
  }

  {
    const key = "height";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["double"](value, {
        context: `${context}'s 'height' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 1;
    }
  }

  {
    const key = "isPrimary";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["boolean"](value, {
        context: `${context}'s 'isPrimary' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = false;
    }
  }

  {
    const key = "persistentDeviceId";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["long"](value, {
        context: `${context}'s 'persistentDeviceId' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 0;
    }
  }

  {
    const key = "pointerId";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["long"](value, {
        context: `${context}'s 'pointerId' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 0;
    }
  }

  {
    const key = "pointerType";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["DOMString"](value, {
        context: `${context}'s 'pointerType' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = "";
    }
  }

  {
    const key = "predictedEvents";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      if (!utils.isObject(value)) {
        throw new globalObject.TypeError(
          `${context}'s 'predictedEvents' member is not an iterable object.`,
        );
      } else {
        const V = [];
        const tmp = value;
        for (let nextItem of tmp) {
          nextItem = PointerEvent.convert(globalObject, nextItem, {
            context: `${context}'s 'predictedEvents' member's element`,
          });

          V.push(nextItem);
        }
        value = V;
      }

      ret[key] = value;
    } else {
      ret[key] = [];
    }
  }

  {
    const key = "pressure";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["float"](value, {
        context: `${context}'s 'pressure' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 0;
    }
  }

  {
    const key = "tangentialPressure";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["float"](value, {
        context: `${context}'s 'tangentialPressure' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 0;
    }
  }

  {
    const key = "tiltX";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["long"](value, {
        context: `${context}'s 'tiltX' member`,
        globals: globalObject,
      });

      ret[key] = value;
    }
  }

  {
    const key = "tiltY";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["long"](value, {
        context: `${context}'s 'tiltY' member`,
        globals: globalObject,
      });

      ret[key] = value;
    }
  }

  {
    const key = "twist";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["long"](value, {
        context: `${context}'s 'twist' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 0;
    }
  }

  {
    const key = "width";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["double"](value, {
        context: `${context}'s 'width' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 1;
    }
  }
};

exports.convert = (globalObject, obj, { context = "The provided value" } = {}) => {
  if (obj !== undefined && typeof obj !== "object" && typeof obj !== "function") {
    throw new globalObject.TypeError(`${context} is not an object.`);
  }

  const ret = Object.create(null);
  exports._convertInherit(globalObject, obj, ret, { context });
  return ret;
};
