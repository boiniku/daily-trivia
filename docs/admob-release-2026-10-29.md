# AdMob production release

- App Store public version checked on 2026-10-29: iOS 1.1.3 (155).
- EAS also has an existing TestFlight build: iOS 1.1.4 (156).
- Both existing builds request the `staging` update channel. Their runtimes are
  `1.1.3` and `1.1.4`, respectively; each requires its own compatible OTA update.
- Advertising repairs use the corresponding released source commits with the
  production public environment variables. Uncommitted work is excluded.
- The new store build is iOS 1.1.5 (157), built with the `production` profile.

## Store build settings

Both `production` and `testflight` now select the production EAS environment,
`EXPO_PUBLIC_APP_ENV=production`, the production update channel, and the Release
iOS build configuration. A build tested through TestFlight can therefore be
promoted to the App Store without retaining a staging configuration.

Development and preview builds use separate `development` and `preview`
channels. Do not publish test updates to `staging`: already published store
builds still subscribe to it.

`eas-build-post-install` runs `scripts/verify-build-ads.js` on EAS servers before
the native build. Store builds fail when an ad unit is missing, uses Google's
sample publisher, belongs to a different publisher than the native app ID, or
when the purchases SDK key or environment/channel settings are unsuitable.
Credential values are never written in the error messages.

## Validation

Run `npm run typecheck`, `node --test tests/*.test.cjs`, and
`npm run verify:release` in `apps/mobile`. Public advertising variables are
provided by the EAS production environment, rather than committed `.env` files.

The OTA patch is applied after download and a subsequent app restart under the
existing native update configuration. It does not replace the original bundle
embedded in fresh installations; 1.1.5 includes production settings from its
first launch.

## Published repair and completed build

- Legacy channel `staging` points to the dedicated `production-admob-repair`
  branch. This is a production delivery route for existing store installations.
- iOS 1.1.3 update group: `70bc1ff6-85fc-42be-8f66-6a1155bbe969`.
  Source: `9d4626513f704c70eabf6ee6c8006b09b41b085e`.
- iOS 1.1.4 update group: `4a337e95-bae5-4c7b-8786-3870ba1fc388`.
  Source: `3fe366f4a2aafb5db9da7569338698168335e652`.
- Both runtimes were requested through the actual Expo update protocol. The
  served bundle matched the locally validated artifact hash and contained the
  production banner/interstitial IDs.
- Production build ID: `ba203365-ef55-4695-ba7f-a25df9adb960`.
  Build source: `7f830f866459f795246cf63c944f27ae33e6be21`.
- The completed 1.1.5 (157) IPA was downloaded and its native production channel,
  runtime version, AdMob app ID, production ad unit IDs, and API URL verified.
- TypeScript validation and all 126 mobile tests passed. The production
  advertisement validation hook also passed on the EAS build server.
- Scheduled App Store Connect upload ID:
  `4784a4de-5f4c-438e-8dfd-b176b89edc90`. Upload completion and Apple review are
  distinct steps; this identifier does not by itself imply review submission.
