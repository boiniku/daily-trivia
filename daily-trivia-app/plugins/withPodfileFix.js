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

                // NUCLEAR FIX:
                // React Native 0.81+ requires Xcode 16.1+.
                // Xcode 16 defaults to signing everything in Pods.
                // We cannot manage Team IDs for every random Pod dependency.
                // STRATEGY: Aggressively DISABLE signing for ALL Pod targets.
                // The main application will still be signed by EAS, which includes the embedded Pods.
                const fixCode = `
    puts "[withPodfileFix] Starting GLOBAL signing DISABLE hook..."
    installer.pods_project.targets.each do |target|
      # Apply to ALL targets (Bundles, Static Libs, Frameworks)
      puts "[withPodfileFix]  -> Disabling signing for Pod Target: #{target.name}"
      target.build_configurations.each do |config|
          config.build_settings['CODE_SIGNING_ALLOWED'] = 'NO'
          config.build_settings['CODE_SIGNING_REQUIRED'] = 'NO'
          config.build_settings['CODE_SIGN_IDENTITY'] = ''
          config.build_settings['EXPANDED_CODE_SIGN_IDENTITY'] = ''
          config.build_settings.delete('DEVELOPMENT_TEAM')
      end
    end
    puts "[withPodfileFix] Finished GLOBAL signing DISABLE hook."
`;

                const hookMarker = "puts \"[withPodfileFix] Starting GLOBAL signing DISABLE hook...\"";

                if (!podfileContent.includes(hookMarker)) {
                    // Clean up previous attempts (Regex to remove old blocks if possible would be nice, but checking duplicates is safer)

                    if (podfileContent.includes('post_install do |installer|')) {
                        console.log('[withPodfileFix] Injecting GLOBAL fix into existing post_install block.');
                        podfileContent = podfileContent.replace(
                            'post_install do |installer|',
                            `post_install do |installer|${fixCode}`
                        );
                    } else {
                        console.log('[withPodfileFix] Appending new post_install block with GLOBAL fix.');
                        podfileContent += `
post_install do |installer|
${fixCode}
end
`;
                    }

                    fs.writeFileSync(podfilePath, podfileContent);
                    console.log('[withPodfileFix] Applied GLOBAL signing DISABLE fix to Podfile.');
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
