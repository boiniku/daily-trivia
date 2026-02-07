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

                // Check if the fix is already applied
                if (!podfileContent.includes('CODE_SIGNING_ALLOWED')) {
                    const fix = `
    installer.pods_project.targets.each do |target|
      if target.respond_to?(:product_type) and target.product_type == "com.apple.product-type.bundle"
        target.build_configurations.each do |config|
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'NO'
        end
      end
    end
`;
                    // Insert the fix inside the existing post_install block
                    // Expo's default Podfile usually ends with:
                    // post_install do |installer|
                    //   ...
                    // end

                    // We look for the last "end" of the post_install block. 
                    // But blindly replacing the last "end" is risky.
                    // Safer strategy: Find "react_native_post_install(installer)" and insert after it.

                    if (podfileContent.includes('react_native_post_install(installer)')) {
                        podfileContent = podfileContent.replace(
                            'react_native_post_install(installer)',
                            `react_native_post_install(installer)\n${fix}`
                        );
                        fs.writeFileSync(podfilePath, podfileContent);
                        console.log('[withPodfileFix] Applied resource bundle signing fix to Podfile.');
                    } else {
                        console.warn('[withPodfileFix] Could not find react_native_post_install in Podfile, skipping fix.');
                    }
                }
            }
            return config;
        },
    ]);
};

module.exports = withPodfileFix;
