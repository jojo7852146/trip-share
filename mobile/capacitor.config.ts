import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.tripshare.app',
  appName: '旅行分享',
  webDir: 'www',
  server: {
    url: 'http://8.134.168.105:500',
    cleartext: true
  },
  android: {
    allowMixedContent: true
  }
};

export default config;
