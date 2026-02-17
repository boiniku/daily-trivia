import { requireOptionalNativeModule } from 'expo-modules-core';

// Use requireOptionalNativeModule to avoid crash if native module is not available
// (e.g., on Android or when the native module fails to initialize)
const WidgetControl = requireOptionalNativeModule('WidgetControl');

export function reloadAllTimelines() {
    if (WidgetControl && WidgetControl.reloadAllTimelines) {
        WidgetControl.reloadAllTimelines();
    } else {
        console.warn("WidgetControl.reloadAllTimelines is not available");
    }
}
