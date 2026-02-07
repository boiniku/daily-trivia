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
                // Using 'Automatic' style is safer when we provide a team.
                const fixCode = `
    puts "[withPodfileFix] Starting signing injection hook..."
    installer.pods_project.targets.each do |target|
      product_type = target.respond_to?(:product_type) ? target.product_type : "unknown"
      
      # Targeted approach: Only fix bundles or specific SDKs that are known to fail
      # We check for 'bundle' product type OR specific pod names
      if (product_type == "com.apple.product-type.bundle") or (target.name.include?("Google-Mobile-Ads-SDK"))
        puts "[withPodfileFix]  -> Applying Development Team to #{target.name}"
        target.build_configurations.each do |config|
            # Ensure signing is ENABLED and use the correct Team ID
            config.build_settings['CODE_SIGNING_ALLOWED'] = 'YES'
            config.build_settings['CODE_SIGNING_REQUIRED'] = 'YES'
            config.build_settings['CODE_SIGN_STYLE'] = 'Automatic'
            config.build_settings['DEVELOPMENT_TEAM'] = '86V3PV77T6' 
        end
      end
    end
    puts "[withPodfileFix] Finished signing injection hook."
`;

                if (!podfileContent.includes("puts \"[withPodfileFix] Starting signing injection hook...\"")) {

                    if (podfileContent.includes('post_install do |installer|')) {
                        console.log('[withPodfileFix] Injecting signing fix into existing post_install block.');
                        podfileContent = podfileContent.replace(
                            'post_install do |installer|',
                            `post_install do |installer|${fixCode}`
                        );
                    } else {
                        console.log('[withPodfileFix] Appending new post_install block with signing fix.');
                        podfileContent += `
post_install do |installer|
${fixCode}
end
`;
                    }

                    fs.writeFileSync(podfilePath, podfileContent);
                    console.log('[withPodfileFix] Applied resource bundle signing fix (Team ID injection) to Podfile.');
                } else {
                    console.log('[withPodfileFix] Signing fix already present in Podfile.');
                }
            } else {
                console.warn('[withPodfileFix] Podfile not found at ' + podfilePath);
            }
            return config;
        },
    ]);
};

module.exports = withPodfileFix;
