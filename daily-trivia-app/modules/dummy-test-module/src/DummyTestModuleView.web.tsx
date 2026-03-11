import * as React from 'react';

import { DummyTestModuleViewProps } from './DummyTestModule.types';

export default function DummyTestModuleView(props: DummyTestModuleViewProps) {
  return (
    <div>
      <iframe
        style={{ flex: 1 }}
        src={props.url}
        onLoad={() => props.onLoad({ nativeEvent: { url: props.url } })}
      />
    </div>
  );
}
