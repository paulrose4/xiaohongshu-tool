import React from 'react';

const LogViewer = () => {
  const [logs, setLogs] = React.useState([]);

  // 模拟日志
  React.useEffect(() => {
    const timers = [];
    const logMessages = [
      "[selector] querying candidates for: 测试选品",
      "[selector] mock source returned 5 items",
      "[selector] filter 19.9-69.9元 / 佣金>20% / 销量>5000: 4/5 passed",
      "[visual] downloading white-bg image: https://picsum.photos/seed/xhs-laundry-basket/800/800",
      "[visual] removing background via rmbg",
      "[visual] compositing onto cozy-room background + big text banner",
      "[visual] composite saved: E:/titkok/assets/output/composite_62f05786.jpg",
      "[copy] generating copy via deepseek/deepseek-v4-pro",
      "[copy] WARNING: no LLM api key configured",
      "[copy] ERROR: LLM call failed: Error code: 401"
    ];
    
    logMessages.forEach((msg, index) => {
      const timer = setTimeout(() => {
        setLogs(prev => [...prev, msg]);
      }, index * 1000);
      timers.push(timer);
    });

    return () => {
      timers.forEach(timer => clearTimeout(timer));
    };
  }, []);

  return (
    <div className="bg-gray-900 text-green-400 p-4 rounded font-mono text-sm h-64 overflow-y-auto">
      {logs.map((log, index) => (
        <div key={index} className="mb-1">{log}</div>
      ))}
    </div>
  );
};

export default LogViewer;