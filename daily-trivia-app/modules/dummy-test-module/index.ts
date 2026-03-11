// Reexport the native module. On web, it will be resolved to DummyTestModule.web.ts
// and on native platforms to DummyTestModule.ts
export { default } from './src/DummyTestModule';
export { default as DummyTestModuleView } from './src/DummyTestModuleView';
export * from  './src/DummyTestModule.types';
