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

                // Hardcoded Team ID from logs: 86V3PV77T6
                // Refined Fix: ONLY apply to resource bundles, NOT static libraries.
                const fixCode = `
    puts "[withPodfileFix] Starting precise signing injection hook..."
    installer.pods_project.targets.each do |target|
      product_type = target.respond_to?(:product_type) ? target.product_type : "unknown"
      
      # STRICT CHECK: Only Resource Bundles need this fix.
      # Static Libraries (com.apple.product-type.library.static) must NOT be signed this way.
      if (product_type == "com.apple.product-type.bundle")
        puts "[withPodfileFix]  -> Applying Development Team to Resource Bundle: #{target.name}"
        target.build_configurations.each do |config|
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'YES'
            config.build_settings['CODE_SIGNING_REQUIRED'] = 'YES'
            config.build_settings['CODE_SIGN_STYLE'] = 'Automatic'
            config.build_settings['DEVELOPMENT_TEAM'] = '86V3PV77T6'
            # Force identity to match the team if needed, but Automatic usually handles it
            config.build_settings['CODE_SIGN_IDENTITY'] = 'Apple Development' 
        end
      end
    end
    puts "[withPodfileFix] Finished precise signing injection hook."
`;

                if (!podfileContent.includes("puts \"[withPodfileFix] Starting precise signing injection hook...\"")) {

                    if (podfileContent.includes('post_install do |installer|')) {
                        console.log('[withPodfileFix] Injecting precise signing fix into existing post_install block.');
                        podfileContent = podfileContent.replace(
                            'post_install do |installer|',
                            `post_install do |installer|${fixCode}`
                        );
                    } else {
                        console.log('[withPodfileFix] Appending new post_install block with precise signing fix.');
                        podfileContent += `
post_install do |installer|
${fixCode}
end
`;
                    }

                    fs.writeFileSync(podfilePath, podfileContent);
                    console.log('[withPodfileFix] Applied precise resource bundle signing fix to Podfile.');
                } else {
                    console.log('[withPodfileFix] Precise signing fix already present in Podfile.');
                }
            } else {
                console.warn('[withPodfileFix] Podfile not found at ' + podfilePath);
            }
            return config;
        },
    ]);
};

module.exports = withPodfileFix;
