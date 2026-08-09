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
      // AND force Development Team (Fix for "signed by default" error)
      // Robust fix for "resource bundles signed by default" error in Xcode 14+
      // Instead of complicating with Team IDs, simply disable signing for resource bundles.
      // This is the most common and successful fix in the community.
      const fixCode = `
    installer.pods_project.targets.each do |target|
      target.build_configurations.each do |config|
          config.build_settings['CLANG_ALLOW_NON_MODULAR_INCLUDES_IN_FRAMEWORK_MODULES'] = 'YES'
      end
      if target.respond_to?(:product_type) and target.product_type == "com.apple.product-type.bundle"
        target.build_configurations.each do |config|
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'NO'
            config.build_settings['CODE_SIGNING_REQUIRED'] = 'NO'
            config.build_settings['CODE_SIGN_IDENTITY'] = ''
            config.build_settings['EXPANDED_CODE_SIGN_IDENTITY'] = ''
        end
      end
    end
`;

      // Robust insertion:
      // 1. Try to find the start of the post_install block
      if (podfileContent.includes('post_install do |installer|')) {
        podfileContent = podfileContent.replace(
          'post_install do |installer|',
          `post_install do |installer|${fixCode}`
        );
      } else {
        // 2. If not found (unlikely), append a new block
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
