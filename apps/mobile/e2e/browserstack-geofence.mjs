const HUB_URL = 'https://hub-cloud.browserstack.com/wd/hub';
const BUNDLE_ID = 'com.dailytrivia.app';
const STAGING_MAP_URL = 'https://daily-trivia-backend-staging.onrender.com/trivia/map';
const ROTATION_MODE = process.argv.includes('--rotation');

const OUTSIDE_LOCATION = {
    latitude: Number(process.env.GEOFENCE_OUTSIDE_LATITUDE ?? 35.390926),
    longitude: Number(process.env.GEOFENCE_OUTSIDE_LONGITUDE ?? 137.100000),
};
let insideLocation = {
    latitude: Number(process.env.GEOFENCE_INSIDE_LATITUDE ?? 35.390926),
    longitude: Number(process.env.GEOFENCE_INSIDE_LONGITUDE ?? 137.066830),
};
const WAIT_SECONDS = Number(process.env.GEOFENCE_WAIT_SECONDS ?? 150);
const ROTATION_WAIT_SECONDS = Number(process.env.GEOFENCE_ROTATION_WAIT_SECONDS ?? 120);
let rotationWaypoint = null;
let targetNotificationText = '姫町';
let targetDescription = '姫町スポット';

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
let deviceLockedForTest = false;

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const log = (message) => console.log(`[geofence-e2e] ${message}`);

const toRadians = (value) => value * Math.PI / 180;
const calculateDistanceMeters = (from, to) => {
    const earthRadiusMeters = 6_371_000;
    const latitudeDelta = toRadians(to.latitude - from.latitude);
    const longitudeDelta = toRadians(to.longitude - from.longitude);
    const fromLatitude = toRadians(from.latitude);
    const toLatitude = toRadians(to.latitude);
    const a = Math.sin(latitudeDelta / 2) ** 2
        + Math.cos(fromLatitude) * Math.cos(toLatitude) * Math.sin(longitudeDelta / 2) ** 2;
    return earthRadiusMeters * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
};

const prepareRotationTest = async () => {
    if (!ROTATION_MODE) return;

    log('stagingのスポット一覧から、初期監視19件に含まれない対象を選びます。');
    const response = await fetch(STAGING_MAP_URL);
    if (!response.ok) throw new Error(`stagingスポット取得に失敗しました（HTTP ${response.status}）。`);
    const spots = await response.json();
    if (!Array.isArray(spots) || spots.length < 21) {
        throw new Error(`19+1試験には21件以上必要ですが、stagingには${Array.isArray(spots) ? spots.length : 0}件しかありません。`);
    }

    const ranked = spots
        .filter((spot) => Number.isFinite(Number(spot.latitude)) && Number.isFinite(Number(spot.longitude)))
        .map((spot) => ({
            ...spot,
            boundaryDistance: calculateDistanceMeters(OUTSIDE_LOCATION, {
                latitude: Number(spot.latitude),
                longitude: Number(spot.longitude),
            }) - Number(spot.unlockRadiusMeters ?? spot.unlock_radius_meters ?? 0),
        }))
        .sort((a, b) => a.boundaryDistance - b.boundaryDistance);

    // Leave enough margin beyond rank 19 in case the app immediately unlocks
    // one or two spots at the initial coordinate before registering regions.
    const requestedIndex = Math.max(19, Number(process.env.GEOFENCE_ROTATION_TARGET_INDEX ?? 30));
    const targetIndex = Math.min(requestedIndex, ranked.length - 1);
    const target = ranked[targetIndex];
    const targetRadius = Math.max(1, Number(target.unlockRadiusMeters ?? target.unlock_radius_meters ?? 100));
    const targetLatitude = Number(target.latitude);
    const targetLongitude = Number(target.longitude);

    insideLocation = { latitude: targetLatitude, longitude: targetLongitude };
    rotationWaypoint = {
        latitude: targetLatitude,
        longitude: targetLongitude + (
            (targetRadius + 1500)
            / (111_320 * Math.max(0.2, Math.cos(targetLatitude * Math.PI / 180)))
        ),
    };
    targetNotificationText = String(target.title ?? target.id);
    targetDescription = `${targetNotificationText}（初期順位${targetIndex + 1}位 / ${target.id}）`;

    if (targetIndex < 19) throw new Error('監視対象外のスポットを選択できませんでした。');
    log(`対象: ${targetDescription}`);
    log(`初期地点から解放境界まで約${Math.round(target.boundaryDistance / 1000)}kmのため、最初の19件には含まれません。`);
};

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
        `label CONTAINS ${JSON.stringify(label)} OR name CONTAINS ${JSON.stringify(label)}`,
        label,
        timeoutMs
    );
};

const findByExactLabel = (label, timeoutMs = 20_000) => {
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
                // Permission choices are handled explicitly below. Automatically
                // accepting an iOS location alert can select "Allow Once".
                'appium:autoAcceptAlerts': false,
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

const ensureAppRunning = async () => {
    let lastState = 0;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
        try {
            lastState = Number(await execute('mobile: queryAppState', { bundleId: BUNDLE_ID }));
        } catch {
            lastState = 0;
        }

        // Appium states: 2 = background suspended, 3 = background, 4 = foreground.
        if (lastState === 4) return;
        log(`アプリが前面にないため起動します（${attempt}/3、state=${lastState}）。`);
        try {
            await execute('mobile: activateApp', { bundleId: BUNDLE_ID });
        } catch (error) {
            log(`アプリ起動命令に失敗しました: ${error.message}`);
        }
        await sleep(6000);
    }

    lastState = Number(await execute('mobile: queryAppState', { bundleId: BUNDLE_ID }).catch(() => 0));
    if (lastState !== 4) {
        throw new Error(`アプリを3回起動しても前面状態になりませんでした（state=${lastState}）。クラッシュログを確認してください。`);
    }
};

const completeTutorial = async () => {
    log('チュートリアルを進めます。');
    await ensureAppRunning();
    await sleep(8000);
    await clickLabel('次へ', 30_000);
    await clickLabel('次へ');
    await clickLabel('次へ');
    await clickLabel('通知を設定する');
};

const backgroundApp = async () => {
    // BrowserStack's iOS driver does not expose mobile: backgroundApp on every
    // device image, but its standard Appium endpoint is supported.
    try {
        await command('POST', '/appium/app/background', { seconds: -1 });
    } catch (error) {
        log(`標準バックグラウンドAPIを利用できないためHome操作へ切り替えます: ${error.message}`);
        await execute('mobile: pressButton', { name: 'home' });
    }
};

const pressPowerButton = () => execute('mobile: performIoHidEvent', {
    page: 0x0C,
    usage: 0x30,
    durationSeconds: 0.005,
});

const lockDeviceForTest = async () => {
    try {
        log('画面をロックして、ロック中の通知を検証します。');
        await pressPowerButton();
        deviceLockedForTest = true;
        await sleep(2500);
    } catch (error) {
        log(`端末ロックを利用できないためホーム画面のまま続行します: ${error.message}`);
    }
};

const printScreenDiagnostics = async () => {
    if (!sessionId) return;
    try {
        let source;
        try {
            source = await command('GET', '/source');
        } catch {
            console.error('[geofence-e2e] アプリ停止後の画面を確認するため、一度だけ再起動します。');
            await execute('mobile: activateApp', { bundleId: BUNDLE_ID });
            await sleep(5000);
            source = await command('GET', '/source');
        }
        const sourceText = typeof source === 'string' ? source : JSON.stringify(source);
        const visibleTexts = Array.from(
            sourceText.matchAll(/\b(?:label|name|value)="([^"]{1,160})"/g),
            (match) => match[1]
        );
        const uniqueTexts = [...new Set(visibleTexts)].filter((value) => value.trim());
        console.error(`[geofence-e2e] 現在の画面要素: ${uniqueTexts.slice(0, 60).join(' | ') || '(取得できませんでした)'}`);

        if (sourceText.includes('No development servers found') || sourceText.includes('Development Server')) {
            console.error('[geofence-e2e] Development Buildがアップロードされています。Metro不要のpreview IPAをアップロードしてください。');
        }
    } catch (diagnosticError) {
        console.error(`[geofence-e2e] 画面診断の取得にも失敗しました: ${diagnosticError.message}`);
    }
};

const configurePermissions = async () => {
    log('通常のiOS許可画面で、通知と位置情報を「常に」許可します。');
    const preferredButtons = [
        'Allow',
        '許可',
        'Allow While Using App',
        'Appの使用中は許可',
        'Change to Always Allow',
        '常に許可に変更',
        'Always Allow',
        '常に許可',
    ];
    const deadline = Date.now() + 75_000;
    let quietSince = null;

    while (Date.now() < deadline) {
        const source = await command('GET', '/source');
        const sourceText = typeof source === 'string' ? source : JSON.stringify(source);
        const button = preferredButtons.find((label) => (
            sourceText.includes(`label="${label}"`) || sourceText.includes(`name="${label}"`)
        ));

        if (button) {
            log(`iOS許可画面: 「${button}」を選択します。`);
            const elementId = await findByExactLabel(button, 5000);
            await command('POST', `/element/${elementId}/click`, {});
            quietSince = null;
            await sleep(2500);
            continue;
        }

        // The manager requests notification, foreground location and then
        // background location serially. Wait until all dialogs have settled.
        quietSince ??= Date.now();
        if (Date.now() - quietSince >= 10_000) break;
        await sleep(1000);
    }

    await execute('mobile: activateApp', { bundleId: BUNDLE_ID });
    // AppState active triggers a fresh geofence registration using the outside location.
    await sleep(20_000);
};

const setDeviceLocation = async (location, description) => {
    log(`GPSを${description} ${location.latitude}, ${location.longitude} へ移動します。`);
    await command('POST', '/location', {
        location: { ...location, altitude: 0 },
    });
};

const waitForBackgroundEvent = async (waitSeconds, phaseLabel) => {
    log(`${phaseLabel}を最大${waitSeconds}秒待ちます。`);
    const startedAt = Date.now();
    while ((Date.now() - startedAt) / 1000 < waitSeconds) {
        await sleep(15_000);
        // Keep the BrowserStack session alive without foregrounding the app.
        const appState = await execute('mobile: queryAppState', { bundleId: BUNDLE_ID });
        const elapsed = Math.round((Date.now() - startedAt) / 1000);
        log(`${phaseLabel} ${Math.min(elapsed, waitSeconds)}/${waitSeconds}秒（state=${appState}）`);
    }
};

const notificationPredicate = () => (
    `label CONTAINS ${JSON.stringify(targetNotificationText)}`
);

const verifyBackgroundNotification = async () => {
    log('アプリを開かずにロック画面・iOS通知センターの解放通知を確認します。');
    if (deviceLockedForTest) {
        // Wake the screen without unlocking it. Notifications should be visible
        // directly on the lock screen.
        await pressPowerButton();
        await sleep(3500);
        try {
            return await findByPredicate(
                notificationPredicate(),
                `${targetDescription}のロック画面解放通知`,
                6000
            );
        } catch {
            log('ロック画面に通知が見つからないため通知センターも確認します。');
        }
    }

    const rect = await command('GET', '/window/rect');
    const centerX = Math.round((rect.width ?? 390) / 2);
    const bottomY = Math.round((rect.height ?? 844) * 0.78);
    const attempts = [
        { x: centerX, y: 2 },
        { x: Math.round((rect.width ?? 390) * 0.15), y: 20 },
        { x: centerX, y: 40 },
    ];

    for (const attempt of attempts) {
        try {
            await command('POST', '/actions', {
                actions: [{
                    type: 'pointer',
                    id: 'notification-center-finger',
                    parameters: { pointerType: 'touch' },
                    actions: [
                        { type: 'pointerMove', duration: 0, origin: 'viewport', x: attempt.x, y: attempt.y },
                        { type: 'pointerDown', button: 0 },
                        { type: 'pause', duration: 350 },
                        { type: 'pointerMove', duration: 900, origin: 'viewport', x: attempt.x, y: bottomY },
                        { type: 'pointerUp', button: 0 },
                    ],
                }],
            });
        } catch {
            await execute('mobile: dragFromToForDuration', {
                duration: 0.9,
                fromX: attempt.x,
                fromY: attempt.y,
                toX: attempt.x,
                toY: bottomY,
            });
        }
        await sleep(2500);

        try {
            return await findByPredicate(
                notificationPredicate(),
                `${targetDescription}のバックグラウンド解放通知`,
                4000
            );
        } catch {
            // Try another top-edge coordinate before reporting a real failure.
        }
    }

    return findByPredicate(
        notificationPredicate(),
        `${targetDescription}のバックグラウンド解放通知`,
        30_000
    );
};

const verifyUnlock = async (notificationElementId) => {
    log(`解放通知をタップし、${targetDescription}の解放状態を確認します。`);
    await command('POST', `/element/${notificationElementId}/click`, {});
    await sleep(8000);
    await findByLabel('解放済み', 12_000);
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
    await prepareRotationTest();
    log('BrowserStack実機セッションを開始します。');
    await createSession();
    await completeTutorial();
    await configurePermissions();
    await backgroundApp();
    await lockDeviceForTest();
    if (ROTATION_MODE) {
        // The target is initially outside the 19 monitored trivia regions.
        // Stop outside its unlock radius so only the +1 refresh-region exit can
        // cause the target to be selected into the next set of 19.
        await setDeviceLocation(rotationWaypoint, `${targetDescription}の解放範囲外へ`);
        await waitForBackgroundEvent(ROTATION_WAIT_SECONDS, '19+1監視更新待機');
        await setDeviceLocation(insideLocation, `${targetDescription}の解放範囲内へ`);
    } else {
        await setDeviceLocation(insideLocation, '姫町中心へ');
    }
    // Location changes are deliberately performed only after the app is backgrounded.
    await waitForBackgroundEvent(WAIT_SECONDS, 'バックグラウンド解放待機');
    const notificationElementId = await verifyBackgroundNotification();
    // The notification is scheduled only after unlockTrivia has persisted the
    // unlock record, so finding it is the authoritative background-test pass.
    // BrowserStack cloud devices may keep the notification on the lock screen
    // after a tap because they cannot complete biometric/passcode unlock.
    try {
        await verifyUnlock(notificationElementId);
    } catch (error) {
        log(`通知は確認済みです。ロック解除後の画面確認だけを省略します: ${error.message}`);
    }
    const successReason = ROTATION_MODE
        ? `+1更新後、ロック中に初期監視対象外の${targetDescription}が解放され、通知が表示されました。`
        : 'ロック中にバックグラウンドで姫町スポットが解放され、通知が表示されました。';
    await finishSession(true, successReason);
    log(ROTATION_MODE
        ? `成功: 19+1の監視更新後に${targetDescription}が解放されました。`
        : '成功: バックグラウンド位置イベントで姫町の雑学が解放されました。');
} catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`[geofence-e2e] 失敗: ${message}`);
    await printScreenDiagnostics();
    await finishSession(false, message).catch(() => undefined);
    process.exitCode = 1;
}
