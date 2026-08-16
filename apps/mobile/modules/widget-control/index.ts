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

export async function getWidgetImageBase64(displayTheme: string, timeTheme: string): Promise<string> {
    if (WidgetControl && WidgetControl.getWidgetImageBase64) {
        return await WidgetControl.getWidgetImageBase64(displayTheme, timeTheme);
    }
    console.warn("WidgetControl.getWidgetImageBase64 is not available");
    return "";
}

export async function saveWidgetThemeImage(theme: string, base64: string): Promise<boolean> {
    if (WidgetControl && WidgetControl.saveWidgetThemeImage) {
        return await WidgetControl.saveWidgetThemeImage(theme, base64);
    }
    console.warn("WidgetControl.saveWidgetThemeImage is not available");
    return false;
}

export async function downloadAndSaveWidgetThemeImage(url: string, theme: string): Promise<boolean> {
    if (!WidgetControl) {
        throw new Error("WidgetControl module itself is completely missing in native build.");
    }
    if (!WidgetControl.downloadAndSaveWidgetThemeImage) {
        throw new Error("WidgetControl.downloadAndSaveWidgetThemeImage function is not registered in the native binary.");
    }
    
    // Pass to native and await
    const result = await WidgetControl.downloadAndSaveWidgetThemeImage(url, theme);
    
    // We expect native to return 'true' on success
    if (result !== true) {
        throw new Error(`Native module resolved silently but returned: ${String(result)}`);
    }
    return true;
}

export async function saveAllWidgetImages(): Promise<number> {
    if (WidgetControl && WidgetControl.saveAllWidgetImages) {
        return await WidgetControl.saveAllWidgetImages();
    }
    console.warn("WidgetControl.saveAllWidgetImages is not available");
    return 0;
}

export async function getSavedWidgetFiles(): Promise<any[]> {
    if (WidgetControl && WidgetControl.getSavedWidgetFiles) {
        return await WidgetControl.getSavedWidgetFiles();
    }
    console.warn("WidgetControl.getSavedWidgetFiles is not available");
    return [];
}
