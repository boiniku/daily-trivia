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

                // Robust fix for Xcode 14+ resource bundle signing
                const fixCode = `
    installer.pods_project.targets.each do |target|
      # Fix for Google-Mobile-Ads-SDK and other resource bundles
      if (target.respond_to?(:product_type) and target.product_type == "com.apple.product-type.bundle") or (target.name.include?("Google-Mobile-Ads-SDK"))
        target.build_configurations.each do |config|
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'NO'
            config.build_settings['CODE_SIGNING_REQUIRED'] = 'NO'
            config.build_settings['CODE_SIGNING_IDENTITY'] = '-'
            config.build_settings['EXPANDED_CODE_SIGN_IDENTITY'] = '-'
        end
      end
    end
`;

                // Check if the fix is arguably already there (checking for unique string)
                if (!podfileContent.includes("config.build_settings['CODE_SIGNING_IDENTITY'] = '-'")) {

                    if (podfileContent.includes('post_install do |installer|')) {
                        // Inject into existing post_install block
                        console.log('[withPodfileFix] Injecting robust fix into existing post_install block.');
                        // We replace the start of the block with start + fix
                        podfileContent = podfileContent.replace(
                            'post_install do |installer|',
                            `post_install do |installer|${fixCode}`
                        );
                    } else {
                        // Append new post_install block if not found
                        console.log('[withPodfileFix] Appending new post_install block with robust fix.');
                        podfileContent += `
post_install do |installer|
${fixCode}
end
`;
                    }

                    fs.writeFileSync(podfilePath, podfileContent);
                    console.log('[withPodfileFix] Applied robust resource bundle signing fix to Podfile.');
                } else {
                    console.log('[withPodfileFix] Robust fix already present in Podfile.');
                }
            } else {
                console.warn('[withPodfileFix] Podfile not found at ' + podfilePath);
            }
            return config;
        },
    ]);
};

module.exports = withPodfileFix;
