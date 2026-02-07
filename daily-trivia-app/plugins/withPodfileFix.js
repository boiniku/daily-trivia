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
                // Refined Fix: Apply Team ID to bundles, but let Xcode decide Style/Identity.
                const fixCode = `
    puts "[withPodfileFix] Starting relaxed signing code hook..."
    installer.pods_project.targets.each do |target|
      product_type = target.respond_to?(:product_type) ? target.product_type : "unknown"
      
      # STRICT CHECK: Only Resource Bundles need this fix.
      if (product_type == "com.apple.product-type.bundle")
        puts "[withPodfileFix]  -> Applying Development Team to Resource Bundle: #{target.name}"
        target.build_configurations.each do |config|
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'YES'
            config.build_settings['CODE_SIGNING_REQUIRED'] = 'YES'
            config.build_settings['DEVELOPMENT_TEAM'] = '86V3PV77T6'
            
            # Removed explicit CODE_SIGN_STYLE and CODE_SIGN_IDENTITY
            # asking Xcode to infer them based on the Team ID.
        end
      end
    end
    puts "[withPodfileFix] Finished relaxed signing code hook."
`;

                if (!podfileContent.includes("puts \"[withPodfileFix] Starting relaxed signing code hook...\"")) {

                    if (podfileContent.includes('post_install do |installer|')) {
                        console.log('[withPodfileFix] Injecting relaxed signing fix into existing post_install block.');
                        podfileContent = podfileContent.replace(
                            'post_install do |installer|',
                            `post_install do |installer|${fixCode}`
                        );
                    } else {
                        console.log('[withPodfileFix] Appending new post_install block with relaxed signing fix.');
                        podfileContent += `
post_install do |installer|
${fixCode}
end
`;
                    }

                    fs.writeFileSync(podfilePath, podfileContent);
                    console.log('[withPodfileFix] Applied relaxed resource bundle signing fix to Podfile.');
                } else {
                    console.log('[withPodfileFix] Relaxed signing fix already present in Podfile.');
                }
            } else {
                console.warn('[withPodfileFix] Podfile not found at ' + podfilePath);
            }
            return config;
        },
    ]);
};

module.exports = withPodfileFix;
