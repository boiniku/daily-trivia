const HUB_URL = 'https://hub-cloud.browserstack.com/wd/hub';
const BUNDLE_ID = 'com.dailytrivia.app';

const OUTSIDE_LOCATION = {
    latitude: Number(process.env.GEOFENCE_OUTSIDE_LATITUDE ?? 35.390926),
    longitude: Number(process.env.GEOFENCE_OUTSIDE_LONGITUDE ?? 137.100000),
};
const INSIDE_LOCATION = {
    latitude: Number(process.env.GEOFENCE_INSIDE_LATITUDE ?? 35.390926),
    longitude: Number(process.env.GEOFENCE_INSIDE_LONGITUDE ?? 137.066830),
};
const WAIT_SECONDS = Number(process.env.GEOFENCE_WAIT_SECONDS ?? 150);

const username = process.env.BROWSERSTACK_USERNAME;
const accessKey = process.env.BROWSERSTACK_ACCESS_KEY;
const appId = process.env.BROWSERSTACK_APP_ID;

if (!username || !accessKey || !appId) {
    throw new Error(
        'BROWSERSTACK_USERNAME, BROWSERSTACK_ACCESS_KEY, BROWSERSTACK_APP_ID を同じPowerShellで設定してください。'
    );
}
if (!appId.startsWith('bs://')) {
    throw new Error('BROWSERSTACK_APP_ID は bs:// から始まるApp IDを指定してください。');
}

const auth = Buffer.from(`${username}:${accessKey}`).toString('base64');
let sessionId = null;

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const log = (message) => console.log(`[geofence-e2e] ${message}`);

const webdriverRequest = async (method, path, body) => {
    const response = await fetch(`${HUB_URL}${path}`, {
        method,
        headers: {
            Authorization: `Basic ${auth}`,
            'Content-Type': 'application/json',
        },
        body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    const payload = text ? JSON.parse(text) : {};
    const webdriverError = payload?.value?.error;
    if (!response.ok || webdriverError) {
        const message = payload?.value?.message ?? text ?? `${response.status} ${response.statusText}`;
        throw new Error(`${method} ${path}: ${message}`);
    }
    return payload.value ?? payload;
};

const command = (method, suffix, body) => {
    if (!sessionId) throw new Error('BrowserStack session is not active.');
    return webdriverRequest(method, `/session/${sessionId}${suffix}`, body);
};

const execute = (script, args = {}) => command('POST', '/execute/sync', {
    script,
    args: [args],
});

const browserStackExecutor = (action, args = {}) => execute(
    `browserstack_executor: ${JSON.stringify({ action, arguments: args })}`,
    {}
);

const findByPredicate = async (predicate, description, timeoutMs = 20_000) => {
    const deadline = Date.now() + timeoutMs;
    let lastError;
    while (Date.now() < deadline) {
        try {
            const value = await command('POST', '/element', {
                using: '-ios predicate string',
                value: predicate,
            });
            return value['element-6066-11e4-a52e-4f735466cecf'] ?? value.ELEMENT;
        } catch (error) {
            lastError = error;
            await sleep(1000);
        }
    }
    throw new Error(`「${description}」が見つかりませんでした。${lastError ? ` ${lastError.message}` : ''}`);
};

const findByLabel = (label, timeoutMs = 20_000) => {
    return findByPredicate(
        `label == ${JSON.stringify(label)} OR name == ${JSON.stringify(label)}`,
        label,
        timeoutMs
    );
};

const clickLabel = async (label, timeoutMs) => {
    const elementId = await findByLabel(label, timeoutMs);
    await command('POST', `/element/${elementId}/click`, {});
};

const createSession = async () => {
    const result = await webdriverRequest('POST', '/session', {
        capabilities: {
            alwaysMatch: {
                platformName: 'iOS',
                'appium:automationName': 'XCUITest',
                'appium:deviceName': process.env.BROWSERSTACK_DEVICE ?? 'iPhone 15',
                'appium:platformVersion': process.env.BROWSERSTACK_IOS_VERSION ?? '17',
                'appium:app': appId,
                'appium:autoAcceptAlerts': true,
                'appium:newCommandTimeout': 300,
                'bstack:options': {
                    userName: username,
                    accessKey,
                    projectName: '毎日雑学',
                    buildName: `staging-geofence-${new Date().toISOString().slice(0, 10)}`,
                    sessionName: '姫町 バックグラウンド解放通知',
                    gpsLocation: `${OUTSIDE_LOCATION.latitude},${OUTSIDE_LOCATION.longitude}`,
                    idleTimeout: 300,
                    video: true,
                    deviceLogs: true,
                    appiumLogs: true,
                    debug: true,
                },
            },
        },
    });
    sessionId = result.sessionId;
    if (!sessionId) throw new Error('BrowserStackからsessionIdが返りませんでした。');
};

const setAppPermission = async (permissionSettings) => {
    await browserStackExecutor('updateAppSettings', {
        'Permission Settings': permissionSettings,
    });
    await sleep(2000);
};

const completeTutorial = async () => {
    log('チュートリアルを進めます。');
    await clickLabel('次へ', 30_000);
    await clickLabel('次へ');
    await clickLabel('次へ');
    await clickLabel('通知を設定する');
    await sleep(12_000);
};

const configurePermissions = async () => {
    log('位置情報を「常に」、正確な位置情報と通知をONにします。');
    await setAppPermission({
        Location: { 'ALLOW LOCATION ACCESS': 'Always' },
    });
    await setAppPermission({
        Location: { 'Precise Location': 'ON' },
    });
    await setAppPermission({
        Notifications: { 'Allow Notifications': 'ON' },
    });

    await execute('mobile: activateApp', { bundleId: BUNDLE_ID });
    // AppState active triggers a fresh geofence registration using the outside location.
    await sleep(20_000);
};

const setInsideLocation = async () => {
    log(`GPSを姫町中心 ${INSIDE_LOCATION.latitude}, ${INSIDE_LOCATION.longitude} へ移動します。`);
    try {
        await execute('mobile: setSimulatedLocation', INSIDE_LOCATION);
    } catch (error) {
        log(`setSimulatedLocationを利用できないため標準位置APIへ切り替えます: ${error.message}`);
        await command('POST', '/location', {
            location: { ...INSIDE_LOCATION, altitude: 0 },
        });
    }
};

const waitForBackgroundEvent = async () => {
    log(`バックグラウンド位置イベントを最大${WAIT_SECONDS}秒待ちます。`);
    const startedAt = Date.now();
    while ((Date.now() - startedAt) / 1000 < WAIT_SECONDS) {
        await sleep(15_000);
        // Keep the BrowserStack session alive without foregrounding the app.
        try {
            await execute('mobile: getSimulatedLocation');
        } catch {
            await command('GET', '/location');
        }
        const elapsed = Math.round((Date.now() - startedAt) / 1000);
        log(`バックグラウンド待機 ${Math.min(elapsed, WAIT_SECONDS)}/${WAIT_SECONDS}秒`);
    }
};

const verifyBackgroundNotification = async () => {
    log('アプリを開かずにiOS通知センターを表示し、解放通知を確認します。');
    const rect = await command('GET', '/window/rect');
    const centerX = Math.round((rect.width ?? 390) / 2);
    const bottomY = Math.round((rect.height ?? 844) * 0.78);
    await execute('mobile: dragFromToForDuration', {
        duration: 0.8,
        fromX: centerX,
        fromY: 2,
        toX: centerX,
        toY: bottomY,
    });
    await sleep(3000);

    return findByPredicate(
        'label CONTAINS "この場所ならではの雑学" OR label CONTAINS "が解放されました"',
        '姫町のバックグラウンド解放通知',
        30_000
    );
};

const verifyUnlock = async (notificationElementId) => {
    log('解放通知をタップし、姫町スポットの解放状態を確認します。');
    await command('POST', `/element/${notificationElementId}/click`, {});
    await sleep(8000);
    await findByLabel('解放済み', 30_000);
};

const finishSession = async (passed, reason) => {
    if (!sessionId) return;
    try {
        await browserStackExecutor('setSessionStatus', {
            status: passed ? 'passed' : 'failed',
            reason,
        });
    } catch (error) {
        log(`セッション結果の記録に失敗しました: ${error.message}`);
    }
    try {
        await execute('mobile: resetSimulatedLocation');
    } catch {
        // BrowserStack resets the cloud device after the session as a fallback.
    }
    await webdriverRequest('DELETE', `/session/${sessionId}`);
    sessionId = null;
};

try {
    log('BrowserStack実機セッションを開始します。');
    await createSession();
    await completeTutorial();
    await configurePermissions();
    await execute('mobile: backgroundApp', { seconds: -1 });
    await setInsideLocation();
    // setInsideLocation is deliberately performed only after the app is backgrounded.
    await waitForBackgroundEvent();
    const notificationElementId = await verifyBackgroundNotification();
    await verifyUnlock(notificationElementId);
    await finishSession(true, 'バックグラウンドで姫町スポットが解放されました。');
    log('成功: バックグラウンド位置イベントで姫町の雑学が解放されました。');
} catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[geofence-e2e] 失敗: ${message}`);
    await finishSession(false, message).catch(() => undefined);
    process.exitCode = 1;
}
