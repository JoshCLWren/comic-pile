"use strict";

const conversions = require("webidl-conversions");
const utils = require("./utils.js");

const DeviceMotionEventAccelerationInit = require("./DeviceMotionEventAccelerationInit.js");
const DeviceMotionEventRotationRateInit = require("./DeviceMotionEventRotationRateInit.js");
const EventInit = require("./EventInit.js");

exports._convertInherit = (globalObject, obj, ret, { context = "The provided value" } = {}) => {
  EventInit._convertInherit(globalObject, obj, ret, { context });

  {
    const key = "acceleration";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = DeviceMotionEventAccelerationInit.convert(globalObject, value, {
        context: `${context}'s 'acceleration' member`,
      });

      ret[key] = value;
    }
  }

  {
    const key = "accelerationIncludingGravity";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = DeviceMotionEventAccelerationInit.convert(globalObject, value, {
        context: `${context}'s 'accelerationIncludingGravity' member`,
      });

      ret[key] = value;
    }
  }

  {
    const key = "interval";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = conversions["double"](value, {
        context: `${context}'s 'interval' member`,
        globals: globalObject,
      });

      ret[key] = value;
    } else {
      ret[key] = 0;
    }
  }

  {
    const key = "rotationRate";
    let value = obj === undefined || obj === null ? undefined : obj[key];
    if (value !== undefined) {
      value = DeviceMotionEventRotationRateInit.convert(globalObject, value, {
        context: `${context}'s 'rotationRate' member`,
      });

      ret[key] = value;
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
