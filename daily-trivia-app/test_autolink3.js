const { execSync } = require('child_process');
try {
  const output = execSync('npx expo-modules-autolinking search --platform ios --json').toString();
  const data = JSON.parse(output);
  if (data['widget-control']) {
    console.log(JSON.stringify(data['widget-control'], null, 2));
  } else {
    console.log('widget-control not found!');
  }
} catch (e) {
  console.log('Error:', e.message);
}
