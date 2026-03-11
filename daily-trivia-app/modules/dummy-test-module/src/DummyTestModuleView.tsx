import { requireNativeView } from 'expo';
import * as React from 'react';

import { DummyTestModuleViewProps } from './DummyTestModule.types';

const NativeView: React.ComponentType<DummyTestModuleViewProps> =
  requireNativeView('DummyTestModule');

export default function DummyTestModuleView(props: DummyTestModuleViewProps) {
  return <NativeView {...props} />;
}
