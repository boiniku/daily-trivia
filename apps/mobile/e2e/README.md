# BrowserStack バックグラウンド位置テスト

BrowserStack App Automateの実機iPhoneを使用し、姫町スポットの外側から内側へ
iOSのシステム位置を変更して、バックグラウンド解放を検証します。

## 実行

IPAをBrowserStack App Automateへアップロードした後、同じPowerShellで次を実行します。

```powershell
$env:BROWSERSTACK_USERNAME="BrowserStackのUsername"
$env:BROWSERSTACK_ACCESS_KEY="BrowserStackのAccess Key"
$env:BROWSERSTACK_APP_ID="bs://から始まるApp ID"
npm run test:geofence:browserstack
```

秘密情報は`.env`やGitへ保存しません。標準ではiPhone 15 / iOS 17を使用し、
最大150秒間バックグラウンドイベントを待ちます。

利用可能な端末に合わせて変更する場合:

```powershell
$env:BROWSERSTACK_DEVICE="iPhone 14"
$env:BROWSERSTACK_IOS_VERSION="17"
$env:GEOFENCE_WAIT_SECONDS="180"
npm run test:geofence:browserstack
```

実行後、BrowserStackのApp Automateダッシュボードで動画、Appiumログ、端末ログ、
成功・失敗の理由を確認できます。

## 19+1の監視更新テスト

初期地点から見て30番目前後のスポットをstagingデータから自動選択します。対象の
解放範囲外へ移動して更新用リージョンの退出を発生させ、120秒待ってから対象範囲内へ
移動します。対象名のロック画面通知が届いた場合だけ成功になります。

```powershell
npm run test:geofence-rotation:browserstack
```

対象順位と更新待機時間は必要に応じて変更できます。

```powershell
$env:GEOFENCE_ROTATION_TARGET_INDEX="30"
$env:GEOFENCE_ROTATION_WAIT_SECONDS="150"
npm run test:geofence-rotation:browserstack
```
