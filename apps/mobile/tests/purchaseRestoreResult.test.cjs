const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const { hasProEntitlement, purchaseRestoreNotice } = require('./loadTypescript.cjs')(
    path.resolve(__dirname, '../managers/purchaseRestoreResult.ts'),
);

test('restore reports success only for an active Pro entitlement', () => {
    const info = { entitlements: { active: { pro: { isActive: true } } } };
    assert.equal(hasProEntitlement(info), true);
    assert.equal(purchaseRestoreNotice(info).title, '復元完了');
});

test('no purchases and expired purchases do not report restoration success', () => {
    for (const info of [
        { entitlements: { active: {} } },
        { entitlements: { active: {}, all: { pro: { isActive: false } } } },
        { entitlements: { active: { anotherProduct: {} } } },
    ]) {
        assert.equal(hasProEntitlement(info), false);
        const notice = purchaseRestoreNotice(info);
        assert.equal(notice.title, '有効な購入が見つかりませんでした');
        assert.match(notice.message, /再購入せず/);
    }
});
