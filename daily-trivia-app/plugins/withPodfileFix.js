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

                // HYBRID STRATEGY:
                // 1. Resource Bundles: ENABLE signing + Team ID (fixes "bundles need signing").
                // 2. Static Libraries: DISABLE signing (fixes "empty identity" crash).
                const fixCode = `
    puts "[withPodfileFix] Starting HYBRID signing hook..."
    installer.pods_project.targets.each do |target|
      product_type = target.respond_to?(:product_type) ? target.product_type : "unknown"
      
      target.build_configurations.each do |config|
        if (product_type == "com.apple.product-type.bundle")
            # Case 1: Resource Bundles -> MUST SIGN
            puts "[withPodfileFix]  -> Enabling Signing for Bundle: #{target.name}"
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'YES'
            config.build_settings['CODE_SIGNING_REQUIRED'] = 'YES'
            config.build_settings['CODE_SIGN_STYLE'] = 'Automatic'
            config.build_settings['DEVELOPMENT_TEAM'] = '86V3PV77T6'
            config.build_settings['CODE_SIGN_IDENTITY'] = 'Apple Development' # Fallback default
        elsif (product_type == "com.apple.product-type.library.static")
            # Case 2: Static Libraries -> NO SIGNING allowed (prevents empty identity error)
            # Only apply if it's explicitly a static library pod
            puts "[withPodfileFix]  -> Disabling Signing for Static Lib: #{target.name}"
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'NO'
            config.build_settings['CODE_SIGNING_REQUIRED'] = 'NO'
            config.build_settings.delete('DEVELOPMENT_TEAM')
        end
      end
    end
    puts "[withPodfileFix] Finished HYBRID signing hook."
`;

                if (!podfileContent.includes("puts \"[withPodfileFix] Starting HYBRID signing hook...\"")) {

                    if (podfileContent.includes('post_install do |installer|')) {
                        console.log('[withPodfileFix] Injecting HYBRID signing fix into existing post_install block.');
                        podfileContent = podfileContent.replace(
                            'post_install do |installer|',
                            `post_install do |installer|${fixCode}`
                        );
                    } else {
                        console.log('[withPodfileFix] Appending new post_install block with HYBRID signing fix.');
                        podfileContent += `
post_install do |installer|
${fixCode}
end
`;
                    }

                    fs.writeFileSync(podfilePath, podfileContent);
                    console.log('[withPodfileFix] Applied HYBRID signing fix to Podfile.');
                } else {
                    console.log('[withPodfileFix] HYBRID signing fix already present in Podfile.');
                }
            } else {
                console.warn('[withPodfileFix] Podfile not found at ' + podfilePath);
            }
            return config;
        },
    ]);
};

module.exports = withPodfileFix;
