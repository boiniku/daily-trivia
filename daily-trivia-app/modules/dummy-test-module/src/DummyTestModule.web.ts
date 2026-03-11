import { registerWebModule, NativeModule } from 'expo';

import { ChangeEventPayload } from './DummyTestModule.types';

type DummyTestModuleEvents = {
  onChange: (params: ChangeEventPayload) => void;
}

class DummyTestModule extends NativeModule<DummyTestModuleEvents> {
  PI = Math.PI;
  async setValueAsync(value: string): Promise<void> {
    this.emit('onChange', { value });
  }
  hello() {
    return 'Hello world! 👋';
  }
};

export default registerWebModule(DummyTestModule, 'DummyTestModule');
