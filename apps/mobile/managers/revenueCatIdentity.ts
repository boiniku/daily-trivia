/** Serialize SDK setup/identity transitions and reject stale purchase results. */
export function createRevenueCatIdentity<T>(sdk: {
    configure: (options: { apiKey: string }) => unknown;
    logIn: (id: string) => Promise<{ customerInfo: T }>;
    logOut: () => Promise<T>;
    isAnonymous: () => Promise<boolean>;
    getCustomerInfo: () => Promise<T>;
}, apiKey: string, publish: (info: T | null) => void) {
    let configured: Promise<unknown> | null = null;
    let queue: Promise<unknown> = Promise.resolve();
    let version = 0;
    let readyVersion = -1;
    let requestedIdentity: string | null | undefined;
    const configure = () => {
        if (!apiKey) return Promise.reject(new Error('RevenueCat API key is missing'));
        if (!configured) {
            configured = Promise.resolve().then(() => sdk.configure({ apiKey })).catch((error) => {
                configured = null;
                throw error;
            });
        }
        return configured;
    };
    return {
        setIdentity(id: string | null) {
            // Foreground notifications are refreshes, not account switches.
            // Keep this account's last confirmed entitlement while refreshing.
            if (requestedIdentity !== id) {
                requestedIdentity = id;
                ++version;
                publish(null);
            }
            const revision = version;
            const operation = queue.catch(() => undefined).then(async () => {
                await configure();
                if (revision !== version) return;
                const info = readyVersion === revision ? await sdk.getCustomerInfo()
                    : id ? (await sdk.logIn(id)).customerInfo
                    : await sdk.isAnonymous() ? await sdk.getCustomerInfo() : await sdk.logOut();
                if (revision === version) {
                    readyVersion = revision;
                    publish(info);
                }
            });
            // A failed refresh must not poison later restores/purchases. Initial
            // login failures still fail closed through readyVersion in run().
            queue = operation.catch(() => undefined);
            return operation;
        },
        async run<R>(operation: () => Promise<R>): Promise<R> {
            const revision = version;
            const job = queue.then(async () => {
                if (revision !== version || readyVersion !== revision) throw new Error('購入情報の連携を待ってから再試行してください。');
                const result = await operation();
                if (revision !== version) throw new Error('アカウントが切り替わりました。購入情報を再読み込みしてください。');
                return result;
            });
            // Never switch the SDK's customer while a purchase is in progress.
            queue = job.catch(() => undefined);
            return job;
        },
        accept(info: T) { if (readyVersion === version) publish(info); },
    };
}
