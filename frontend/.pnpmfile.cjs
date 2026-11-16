// TypeScript 7 (the native compiler) has no JavaScript API yet, and some tools need one. The
// project's `typescript` is 7 (tsc, next build); typescript-eslint and openapi-typescript get the
// TS 6 API through Microsoft's compatibility package instead of the project's peer. Remove this
// file once those tools support TypeScript 7.
const TS6 = "npm:@typescript/typescript6@^6.0.2";
const USES_TS_API = /^(@typescript-eslint\/|typescript-eslint$|ts-api-utils$|openapi-typescript$)/;

module.exports = {
  hooks: {
    readPackage(pkg) {
      if (USES_TS_API.test(pkg.name) && pkg.peerDependencies?.typescript) {
        delete pkg.peerDependencies.typescript;
        pkg.dependencies = { ...pkg.dependencies, typescript: TS6 };
      }
      return pkg;
    },
  },
};
