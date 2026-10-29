# Widget initialization and OTA follow-up

The reported TestFlight version is iOS 1.1.5 (157). The Store version still
shows Google's demo advertising creative. The prior advertising updates were
published, but publication did not establish that this user's Store app had
applied one. EAS reported zero installs for the 1.1.3 update and two installs
for the 1.1.4 update at the time of the investigation.

The update endpoint and all 46 files for both updates were downloaded and
verified. The signed app and widget entitlements both contain
`group.com.dailytrivia.app`. The 1.1.5 upload to App Store Connect has finished.
Both `production` and the legacy `staging` channel now point to the dedicated
production repair branch. New preview builds retain their separate channel.

## Widget defects addressed

- Preparing shared credentials depended on Home fetching/restoring cards.
  Startup, foreground and Firebase token changes now initialize widget
  credentials independently of Home.
- Saving the shared cache did not notify WidgetKit to refresh. A successful
  save now calls the existing native reload method after all data is written.
- Empty card responses could erase a usable cache. They are now rejected.
- Token refresh and native widget configuration lookups could wait without a
  limit. They now have bounded waits; an unknown installation never registers
  history.
- Startup credential initialization and card caching are serialized to avoid
  one initialization erasing the other's cache. Account changes invalidate
  stale operations and outgoing credentials/cache are cleared before reuse.
- Failed preference writes are no longer reported as successful widget syncs.

Settings now shows the native version/build, whether an OTA update is running,
and controls to check/apply an additional update or retry widget synchronization.
Applying a downloaded update requires user confirmation in the app before reload.

The changes use existing native methods, with feature detection for older
binaries. Existing 1.1.3/1.1.4/1.1.5 runtimes can receive the JavaScript repair.
Build 1.1.5 (158) embeds the repair from first launch and has been uploaded.
The user subsequently confirmed that the widget displays trivia on their iPhone.

## Delivery evidence

- TypeScript checks and all 137 mobile tests passed.
- Runtime 1.1.3 update group: `3655d939-1972-493f-811b-dd49b04516b5`.
- Runtime 1.1.4 update group: `9460e6f6-4b80-42b9-a0ac-beb6bae0c957`.
- Runtime 1.1.5 update group: `2e4b0db8-0afe-4b30-bf60-6228aa4c5eb0`.
- All three runtimes were requested on both `production` and `staging` using
  the native update protocol. Each returned the expected repair; all 46 files
  were fetched and their SHA-256 hashes checked. The served bundle matched the
  prepared artifact and contained production ad IDs and the widget repair.
- Build 158: `77535b81-1c52-4aa9-bbcd-bcc8234e6e08`, source commit
  `7aa29cd1f9cbb97ce8f36ff08fe6eb267a4c932d`. EAS build status: FINISHED.
- Upload: `6f2e2067-6630-4672-9fab-8891f8069987`. EAS submission status:
  FINISHED. This is upload completion, not Apple review approval.
- The produced IPA was downloaded and checked for native version/build
  1.1.5/158, matching widget extension 1.1.5/158, production update channel,
  production AdMob app/unit IDs, and the new widget initialization functions.

## User confirmation

On 2026-10-29 the user confirmed that the widget now displays trivia. The reply
did not distinguish build 158 from build 157 with the compatible OTA repair.

The user also confirmed that the iPhone is registered as an AdMob test device.
Registered devices receive test-mode advertising even with production ad units:
https://support.google.com/admob/answer/9691433?hl=ja
The continued test creative on that device therefore cannot verify whether a
Store installation uses demo IDs or production IDs. Real ad delivery on an
unregistered device has not been checked. The test-device registration was not
changed.
