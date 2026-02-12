/** @type {import('@bacons/apple-targets').Config} */
module.exports = {
    type: "widget",
    entitlements: {
        "com.apple.security.application-groups": ["group.com.dailytrivia.app"],
    },
    // Ensure the bundle identifier matches the provisioning profile
    bundleIdentifier: "com.dailytrivia.app.TriviaWidgetExtension",
    deploymentTarget: "17.0",
};
