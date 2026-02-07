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

                // Strategy Switch: Disable signing for resource bundles entirely.
                // This resolves the "requires a development team" error by removing the need for a team.
                const fixCode = `
    puts "[withPodfileFix] Starting signing DISABLE hook for bundles..."
    installer.pods_project.targets.each do |target|
      product_type = target.respond_to?(:product_type) ? target.product_type : "unknown"
      
      # TARGET: Resource Bundles only.
      if (product_type == "com.apple.product-type.bundle")
        puts "[withPodfileFix]  -> Disabling signing for Resource Bundle: #{target.name}"
        target.build_configurations.each do |config|
            # Explicitly DISABLE signing
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'NO'
            config.build_settings['CODE_SIGNING_REQUIRED'] = 'NO'
            config.build_settings['CODE_SIGN_IDENTITY'] = ''
            config.build_settings['EXPANDED_CODE_SIGN_IDENTITY'] = ''
            
            # Remove Team ID if present to avoid ambiguity
            config.build_settings.delete('DEVELOPMENT_TEAM')
        end
      end
    end
    puts "[withPodfileFix] Finished signing DISABLE hook."
`;

                if (!podfileContent.includes("puts \"[withPodfileFix] Starting signing DISABLE hook for bundles...\"")) {

                    if (podfileContent.includes('post_install do |installer|')) {
                        console.log('[withPodfileFix] Injecting signing DISABLE fix into existing post_install block.');
                        podfileContent = podfileContent.replace(
                            'post_install do |installer|',
                            `post_install do |installer|${fixCode}`
                        );
                    } else {
                        console.log('[withPodfileFix] Appending new post_install block with signing DISABLE fix.');
                        podfileContent += `
post_install do |installer|
${fixCode}
end
`;
                    }

                    fs.writeFileSync(podfilePath, podfileContent);
                    console.log('[withPodfileFix] Applied signing DISABLE fix to Podfile.');
                } else {
                    console.log('[withPodfileFix] Signing DISABLE fix already present in Podfile.');
                }
            } else {
                console.warn('[withPodfileFix] Podfile not found at ' + podfilePath);
            }
            return config;
        },
    ]);
};

module.exports = withPodfileFix;
