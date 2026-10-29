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
The next iOS build is 1.1.5 (158), embedding the repair from first launch.
Actual display on the user's iPhone still requires confirmation after delivery.
