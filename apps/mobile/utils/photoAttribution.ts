export function safePhotoSourceUrl(value: string): string | null {
    try {
        const url = new URL(value);
        return ['http:', 'https:'].includes(url.protocol) && url.hostname && !url.username && !url.password
            ? url.href : null;
    } catch {
        return null;
    }
}

/** Keep the complete supplied credit; shorten only its always-visible label. */
export function photoAttribution(source: string) {
    const text = source.trim();
    const urls = [...new Set((text.match(/https?:\/\/[^\s<>]+/g) ?? [])
        .map(value => safePhotoSourceUrl(value)).filter((value): value is string => !!value))];
    const licenseUrl = urls.find(url => {
        const parsed = new URL(url);
        return ['creativecommons.org', 'www.creativecommons.org'].includes(parsed.hostname)
            && /^\/(licenses|publicdomain)\//.test(parsed.pathname);
    });
    const sourceUrl = urls.find(url => url !== licenseUrl);
    const credit = text.split(/\r?\n/)[0].trim();
    const author = credit.match(/^(?:写真|撮影|Photo)\s*[：:]\s*(.+?)(?:\s+\/\s+|$)/i)?.[1];
    const license = credit.match(/\bCC\s*(?:BY(?:[ -]SA)?\s*\d(?:\.\d)?|0(?:\s*1\.0)?)\b/i)?.[0];
    const modified = /加工\s*[：:]\s*(?!なし|無し|無加工|none)[^\s]|cropp?ed|modified/i.test(credit);
    const summary = author
        ? ['写真：' + author, license, modified ? '加工あり' : undefined].filter(Boolean).join(' · ')
        : '写真の出典・利用条件';
    return { text, summary, sourceUrl, licenseUrl, license };
}
