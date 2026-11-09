// 云服务连接配置模板：复制为 config.js 后填入实际值（config.js 已 gitignore，不入库）
// 值可在 WorkBuddy 云服务控制台 / 发布信息里查看
window.APP_CONFIG = {
  endpoint: 'https://你的应用域名.app.workbuddy.host',
  oauthRelayBaseUrl: 'https://www.workbuddy.cn/v2/as/genie-baas/oauth',
  publishableKey: 'wbpk_你的publishableKey'
};

// Agent 运行参数（apiBase 留空=自动探测：同源 8000，否则 <host>:8000）
window.AGENT_CONFIG = {
  apiBase: '',
  model: '',        // 留空=从模型目录里挑第一个支持工具调用的
  maxRounds: 6,     // 单次任务最多几次工具往返
  temperature: 0.2  // 诊断要稳，不要发挥
};
