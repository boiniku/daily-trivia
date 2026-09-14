type Entitlements = { entitlements: { active: Record<string, unknown> } };

export const hasProEntitlement = (info: Entitlements | null) => Boolean(info?.entitlements.active.pro);

export function purchaseRestoreNotice(info: Entitlements) {
    return hasProEntitlement(info)
        ? { title: '復元完了', message: 'プレミアムプランの購入を復元しました。' }
        : {
            title: '有効な購入が見つかりませんでした',
            message: 'このアカウントで利用できるプレミアムプランを確認できませんでした。購入時のApp Storeアカウントとアプリのログイン先をご確認ください。購入済みの場合は、再購入せずお問い合わせください。',
        };
}
