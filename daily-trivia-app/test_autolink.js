const { execSync } = require('child_process');
try {
  const output = execSync('npx expo-modules-autolinking search --platform ios --json').toString();
  const data = JSON.parse(output);
  const widgetModule = data.searchResult['widget-control'];
  if (widgetModule) {
    console.log('YES, widget-control is recognized as an Expo module:');
    console.log(JSON.stringify(widgetModule, null, 2));
  } else {
    console.log('NO, widget-control is NOT recognized as an Expo module in the search results.');
  }
} catch (e) {
  console.error('Error running search:', e);
}
