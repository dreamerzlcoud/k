window.inklabAuthReady = fetch('/auth/config', {cache:'no-store'}).then(async response => {
  if (!response.ok) throw new Error('서비스 설정을 불러올 수 없습니다.');
  const config = await response.json();
  if (config.cloud) {
    const auth = await import('/cloud-auth.js');
    await auth.bootstrap(config);
  }
});
