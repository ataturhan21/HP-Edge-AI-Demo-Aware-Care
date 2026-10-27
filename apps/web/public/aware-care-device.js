// The device this web build runs on (ADR-018). The production gateway answers this path with the deployment's device
// from its deploy configuration; this file is the default for development, tests and a gateway without that setting.
window.AWARE_CARE_DEVICE = { name: "HP ZGX Nano", shortName: "ZGX Nano" };
