import { Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { downloadAndSaveWidgetThemeImage } from '../modules/widget-control';

// Cloudflare R2 公開URL（セットアップ後に変更）
const R2_BASE_URL = 'https://pub-9654739f263046168c7fe6c4f4b771ad.r2.dev/widget_themes';

// クラウドから配信するテーマ一覧（RPGは時間帯別）
const CLOUD_THEMES = ['light', 'dark', 'rpg_morning', 'rpg_noon', 'rpg_night', 'cat_morning', 'cat_noon', 'cat_night'] as const;
type CloudTheme = typeof CLOUD_THEMES[number];

const CACHE_KEY_PREFIX = 'widget_theme_cached_';

/**
 * テーマ画像がキャッシュ済みかチェック
 */
async function isThemeCached(theme: string): Promise<boolean> {
    const cached = await AsyncStorage.getItem(`${CACHE_KEY_PREFIX}${theme}`);
    return cached === 'true';
}

export async function downloadAndSaveThemeImage(theme: string): Promise<boolean> {
    if (Platform.OS !== 'ios') return false;

    const extensions = ['jpeg', 'png', 'jpg'];
    let successfulExt = '';
    let targetUrl = '';

    for (const ext of extensions) {
        try {
            const url = `${R2_BASE_URL}/${theme}.${ext}`;
            console.log(`Trying to check theme image: ${theme} from ${url}`);
            
            // Use HEAD request just to check if file exists on R2
            const res = await fetch(url, { method: 'HEAD' });
            if (res.ok) {
                targetUrl = url;
                successfulExt = ext;
                break; // Found the file!
            }
        } catch (e) {
            console.log(`Failed to fetch .${ext} for ${theme}`);
        }
    }

    if (!targetUrl) {
        console.error(`Failed to find ${theme} with any extension (.jpeg, .png, .jpg)`);
        return false;
    }

    try {
        // ネイティブ側で直接URLからダウンロードと保存を行う
        const saved = await downloadAndSaveWidgetThemeImage(targetUrl, theme);
        if (saved) {
            // 保存成功時に、どの拡張子だったかをAsyncStorageに記録（プレビュー表示用）
            await AsyncStorage.setItem(`${CACHE_KEY_PREFIX}${theme}_ext`, successfulExt);
            await AsyncStorage.setItem(`${CACHE_KEY_PREFIX}${theme}`, 'true');
            console.log(`Theme image natively downloaded and saved: ${theme} (was .${successfulExt})`);
        }
        return saved;
    } catch (e) {
        console.error(`Error downloading theme ${theme}:`, e);
        return false;
    }
}

/**
 * 特定テーマの画像を確保（キャッシュ済みならスキップ）
 */
export async function ensureThemeImage(theme: string): Promise<boolean> {
    if (Platform.OS !== 'ios') return false;

    // standard はSwiftUI動的レンダリング、画像不要
    if (theme === 'standard') return true;

    // custom はユーザーが登録するため、ここではスキップ
    if (theme === 'custom') return true;

    // RPG/catは時間帯別に3枚必要 - 常に再ダウンロード（キャッシュ不整合防止）
    if (theme === 'rpg' || theme === 'cat') {
        const variants = [`${theme}_morning`, `${theme}_noon`, `${theme}_night`];
        let allOk = true;
        for (const v of variants) {
            const ok = await downloadAndSaveThemeImage(v);
            if (!ok) allOk = false;
        }
        return allOk;
    }

    // キャッシュ済みならスキップ
    const cached = await isThemeCached(theme);
    if (cached) return true;

    return downloadAndSaveThemeImage(theme);
}

/**
 * 全クラウドテーマの画像を一括ダウンロード
 */
export async function ensureAllThemeImages(): Promise<void> {
    if (Platform.OS !== 'ios') return;

    for (const theme of CLOUD_THEMES) {
        await ensureThemeImage(theme);
    }
}

/**
 * プレビュー用：テーマのR2画像URLを取得する
 * キャッシュ前の段階でプレビューされる可能性を考慮し、正確なURLを返す
 */
export async function getThemeImageUrl(themeName: string): Promise<string | null> {
    const ext = await AsyncStorage.getItem(`${CACHE_KEY_PREFIX}${themeName}_ext`);
    if (ext) {
        return `${R2_BASE_URL}/${themeName}.${ext}`;
    }
    
    // まだダウンロード・キャッシュされていない場合、PNGかJPEGか分からないためHEADリクエストで確認
    for (const testExt of ['jpeg', 'png', 'jpg']) {
        try {
            const url = `${R2_BASE_URL}/${themeName}.${testExt}`;
            const res = await fetch(url, { method: 'HEAD' });
            if (res.ok) {
                return url; // 見つかった有効なURLを返す
            }
        } catch (e) {
            // ignore
        }
    }
    
    // 最終フォールバック
    return `${R2_BASE_URL}/${themeName}.jpeg`;
}

/**
 * キャッシュをクリア（画像更新時に使用）
 */
export async function clearThemeImageCache(theme?: string): Promise<void> {
    if (theme) {
        await AsyncStorage.removeItem(`${CACHE_KEY_PREFIX}${theme}`);
        await AsyncStorage.removeItem(`${CACHE_KEY_PREFIX}${theme}_ext`);
    } else {
        for (const t of CLOUD_THEMES) {
            await AsyncStorage.removeItem(`${CACHE_KEY_PREFIX}${t}`);
            await AsyncStorage.removeItem(`${CACHE_KEY_PREFIX}${t}_ext`);
        }
    }
}

