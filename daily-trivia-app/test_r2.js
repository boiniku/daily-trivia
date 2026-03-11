const https = require('https');

const theme = 'custom';
const exts = ['jpeg', 'png', 'jpg'];
const R2_BASE_URL = 'https://pub-9654739f263046168c7fe6c4f4b771ad.r2.dev/widget_themes';

// Let's test cat_morning which is one of the failing ones
const testTheme = 'cat_morning';

async function checkUrl(url) {
  return new Promise((resolve) => {
    https.request(url, { method: 'HEAD' }, (res) => {
      console.log(`[HEAD] ${url} -> ${res.statusCode}`);
      resolve(res.statusCode === 200);
    }).on('error', (err) => {
      console.error(`Error checking ${url}:`, err.message);
      resolve(false);
    }).end();
  });
}

async function main() {
    for (const ext of exts) {
        const url = `${R2_BASE_URL}/${testTheme}.${ext}`;
        const ok = await checkUrl(url);
        if (ok) {
            console.log(`Success! Found ${url}`);
            return;
        }
    }
    console.log(`Failed to find ${testTheme} with any extension`);
}

main();
