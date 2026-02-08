const { withDangerousMod, withPlugins } = require('@expo/config-plugins');
const fs = require('fs');
const path = require('path');

const withPodfileFix = (config) => {
    return withDangerousMod(config, [
        'ios',
        async (config) => {
            const podfilePath = path.join(config.modRequest.platformProjectRoot, 'Podfile');

            if (!fs.existsSync(podfilePath)) {
                // Should not happen on EAS Build step as prebuild generates it
                console.warn('Is not found Podfile, skipping Podfile fix');
                return config;
            }

            let podfileContent = fs.readFileSync(podfilePath, 'utf8');

            // Code to disable signing for resource bundles (Fix for Xcode 14+)
            const fixCode = `
    installer.pods_project.targets.each do |target|
      if target.respond_to?(:product_type) and target.product_type == "com.apple.product-type.bundle"
        target.build_configurations.each do |config|
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'NO'
        end
      end
    end
`;

            // Insert into the existing post_install block
            if (podfileContent.includes('post_install do |installer|')) {
                podfileContent = podfileContent.replace(
                    'post_install do |installer|',
                    `post_install do |installer|${fixCode}`
                );
            } else {
                // If no post_install block (unlikely in Expo), append it
                podfileContent += `
post_install do |installer|
${fixCode}
end
`;
            }

            fs.writeFileSync(podfilePath, podfileContent);
            return config;
        },
    ]);
};

module.exports = withPodfileFix;
