import { requireNativeModule } from 'expo-modules-core';

// It loads the native module object from the JSI or falls back to
// the bridge module (from NativeModulesProxy) if the remote debugger is on.
const WidgetControl = requireNativeModule('WidgetControl');

export function reloadAllTimelines() {
    if (WidgetControl && WidgetControl.reloadAllTimelines) {
        WidgetControl.reloadAllTimelines();
    } else {
        console.warn("WidgetControl.reloadAllTimelines is not available");
    }
}
