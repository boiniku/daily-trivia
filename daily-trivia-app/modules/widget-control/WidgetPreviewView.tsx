import { requireNativeViewManager } from 'expo-modules-core';
import * as React from 'react';
import { ViewProps } from 'react-native';

export type WidgetPreviewViewProps = {
  displayTheme: string;
  timeTheme: string;
} & ViewProps;

const NativeView: React.ComponentType<WidgetPreviewViewProps> =
  requireNativeViewManager('WidgetControl');

export default function WidgetPreviewView(props: WidgetPreviewViewProps) {
  return <NativeView {...props} />;
}
