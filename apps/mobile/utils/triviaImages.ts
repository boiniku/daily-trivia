export const MAX_TRIVIA_IMAGES = 10;

export function readTriviaImageSources(value: unknown): Record<string, string> | undefined {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
    return Object.fromEntries(Object.entries(value)
        .filter(([image, source]) => image.trim() && typeof source === 'string' && source.trim())
        .map(([image, source]) => [image.trim(), (source as string).trim()]));
}

export function parseTriviaImageSourcesParam(value: unknown): Record<string, string> | undefined {
    const raw = Array.isArray(value) ? value[0] : value;
    if (typeof raw !== 'string' || !raw) return undefined;
    try {
        return readTriviaImageSources(JSON.parse(raw));
    } catch {
        return undefined;
    }
}

// An explicit empty list means the editor removed every photo. Missing or
// malformed lists still support records and cached items from the single-photo API.
export function readTriviaImageUrls(value: unknown): string[] | undefined {
    if (!Array.isArray(value)) return undefined;
    if (value.length === 0) return [];
    const urls = Array.from(new Set(value
        .filter((url): url is string => typeof url === 'string')
        .map(url => url.trim())
        .filter(Boolean)))
        .slice(0, MAX_TRIVIA_IMAGES);
    return urls.length > 0 ? urls : undefined;
}

export function normalizeTriviaImageUrls(imageUrls: unknown, imageUrl?: unknown): string[] {
    const urls = readTriviaImageUrls(imageUrls);
    if (urls !== undefined) return urls;
    return typeof imageUrl === 'string' && imageUrl.trim() ? [imageUrl.trim()] : [];
}

export function parseTriviaImageUrlsParam(value: unknown): string[] | undefined {
    const raw = Array.isArray(value) ? value[0] : value;
    if (typeof raw !== 'string' || !raw) return undefined;
    try {
        return readTriviaImageUrls(JSON.parse(raw));
    } catch {
        return undefined;
    }
}

export function resolveTriviaImageUrl(value: string, baseUrl: string): string {
    if (/^https?:\/\//i.test(value) || /^data:image\//i.test(value)) return value;
    if (/^[a-z][a-z\d+.-]*:/i.test(value)) return '';
    const base = baseUrl.trim().replace(/\/+$/, '');
    const path = value.replace(/^\/+/, '');
    return base && path ? `${base}/${path}` : '';
}
