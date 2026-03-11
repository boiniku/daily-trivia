const fs = require('fs');
try {
  const content = fs.readFileSync('build_info.json', 'utf8');
  // the CLI might have output warnings before the json. let's extract the json part.
  const jsonStart = content.indexOf('{');
  if (jsonStart === -1) {
     console.log('No JSON found');
     process.exit(1);
  }
  const jsonStr = content.substring(jsonStart);
  const data = JSON.parse(jsonStr);
  
  if (data.jobs && data.jobs[0] && data.jobs[0].jobLogsUrl) {
    console.log(data.jobs[0].jobLogsUrl);
  } else if (data.artifacts && data.artifacts.buildUrl) {
    console.log("No jobLogsUrl, but buildUrl:", data.artifacts.buildUrl);
  } else {
    console.log("Could not find logs url in:", Object.keys(data));
  }
} catch (e) {
  console.log('Error:', e.message);
}
