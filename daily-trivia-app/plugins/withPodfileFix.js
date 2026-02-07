const { withDangerousMod } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const withPodfileFix = (config) => {
    return withDangerousMod(config, [
        'ios',
        async (config) => {
            const podfilePath = path.join(config.modRequest.platformProjectRoot, 'Podfile');
            if (fs.existsSync(podfilePath)) {
                let podfileContent = fs.readFileSync(podfilePath, 'utf8');

                // MONKEY-PATCH STRATEGY:
                // Instead of trying to guess where to inject the code to run "last",
                // we monkey-patch the `save` method of the project object.
                // This guarantees our logic runs at the absolute end, just before the project is written to disk,
                // overriding any changes made by standard React Native hooks.

                const fixCode = `
    # [withPodfileFix] Monkey-patch 'save' to ensure fix runs LAST
    # This prevents react_native_post_install from overwriting our changes.
    unless installer.pods_project.respond_to?(:original_save_before_fix)
      puts "[withPodfileFix] Installing save-hook monkey patch..."
      class << installer.pods_project
        alias_method :original_save_before_fix, :save
        
        def save(*args)
          puts "[withPodfileFix] ----------------------------------------------------------------"
          puts "[withPodfileFix] 🐒 Running Late-Stage Signing Fix (inside Project#save) 🐒"
          
          self.targets.each do |target|
            # Apply to ALL targets (Lib, Bundle, Framework)
            # We aggressively disable signing for Pods to avoid Xcode 14/15/16 Team ID requirements.
            target.build_configurations.each do |config|
              config.build_settings['CODE_SIGNING_ALLOWED'] = 'NO'
              config.build_settings['CODE_SIGNING_REQUIRED'] = 'NO'
              config.build_settings['CODE_SIGN_IDENTITY'] = ''
              config.build_settings['EXPANDED_CODE_SIGN_IDENTITY'] = ''
              config.build_settings.delete('DEVELOPMENT_TEAM')
            end
            puts "[withPodfileFix]  -> Disabled signing for: #{target.name}"
          end
          
          puts "[withPodfileFix] ----------------------------------------------------------------"
          original_save_before_fix(*args)
        end
      end
    end
`;

                const hookMarker = "[withPodfileFix] Monkey-patch 'save'";

                if (!podfileContent.includes(hookMarker)) {

                    // Inject specifically at the START of the post_install block.
                    // This creates the hook immediately so it's ready when .save() is called later.
                    if (podfileContent.includes('post_install do |installer|')) {
                        console.log('[withPodfileFix] Injecting Monkey-Patch fix into post_install block.');
                        podfileContent = podfileContent.replace(
                            'post_install do |installer|',
                            `post_install do |installer|${fixCode}`
                        );
                    } else {
                        // Fallback? (Shouldn't happen in managed expo)
                        console.warn('[withPodfileFix] "post_install do |installer|" block not found. Appending one (less robust).');
                        podfileContent += `
post_install do |installer|
${fixCode}
end
`;
                    }

                    fs.writeFileSync(podfilePath, podfileContent);
                    console.log('[withPodfileFix] Applied Monkey-Patch fix to Podfile.');
                } else {
                    console.log('[withPodfileFix] Fix already present.');
                }
            } else {
                console.warn('[withPodfileFix] Podfile not found at ' + podfilePath);
            }
            return config;
        },
    ]);
};

module.exports = withPodfileFix;
