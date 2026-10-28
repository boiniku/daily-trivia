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
