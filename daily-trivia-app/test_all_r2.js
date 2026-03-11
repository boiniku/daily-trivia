const https = require('https');

const R2_BASE_URL = 'https://pub-9654739f263046168c7fe6c4f4b771ad.r2.dev/widget_themes';
const exts = ['jpeg', 'png', 'jpg'];

const themesToCheck = [
    'light', 'dark', 'rpg_morning', 'rpg_noon', 'rpg_night', 'cat_morning', 'cat_noon', 'cat_night'
];

async function checkUrl(url) {
  return new Promise((resolve) => {
    https.request(url, { method: 'HEAD' }, (res) => {
      resolve(res.statusCode === 200);
    }).on('error', (err) => {
      resolve(false);
    }).end();
  });
}

async function main() {
    let allFound = true;
    for (const theme of themesToCheck) {
        let found = false;
        for (const ext of exts) {
            const url = `${R2_BASE_URL}/${theme}.${ext}`;
            const ok = await checkUrl(url);
            if (ok) {
                console.log(`[FOUND] ${theme}.${ext}`);
                found = true;
                break;
            }
        }
        if (!found) {
            console.error(`[MISSING] ${theme} is completely missing!`);
            allFound = false;
        }
    }
    if (allFound) {
        console.log("All themes are present.");
    } else {
        console.log("Some themes are missing!");
    }
}

main();
