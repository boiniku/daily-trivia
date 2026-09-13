const API = 'https://daily-trivia-e7ge.onrender.com';
const REQUIRED_CAPABILITIES = [
  'map_unlock_backup_v2',
  'verified_guest_merge',
  'archived_map_collectibles',
];

const main = async () => {
  const [healthResponse, versionResponse] = await Promise.all([
    fetch(`${API}/health`),
    fetch(`${API}/app/version`),
  ]);
  if (!healthResponse.ok || !versionResponse.ok) {
    throw new Error(`Production API unavailable: health=${healthResponse.status}, version=${versionResponse.status}`);
  }

  const health = await healthResponse.json();
  const version = await versionResponse.json();
  const available = new Set(health.capabilities || []);
  const missing = REQUIRED_CAPABILITIES.filter((item) => !available.has(item));
  if (missing.length) {
    throw new Error(`Production backend is not release-ready. Missing: ${missing.join(', ')}`);
  }
  if (version.latest_version !== '1.1.1') {
    throw new Error(`Production latest_version must be 1.1.1, got ${version.latest_version}`);
  }
  console.log(`Production backend ready: ${health.release_commit || 'unknown commit'}`);
};

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
