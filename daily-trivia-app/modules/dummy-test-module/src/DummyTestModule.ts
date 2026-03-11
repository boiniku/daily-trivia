import { NativeModule, requireNativeModule } from 'expo';

import { DummyTestModuleEvents } from './DummyTestModule.types';

declare class DummyTestModule extends NativeModule<DummyTestModuleEvents> {
  PI: number;
  hello(): string;
  setValueAsync(value: string): Promise<void>;
}

// This call loads the native module object from the JSI.
export default requireNativeModule<DummyTestModule>('DummyTestModule');
