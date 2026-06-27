import React, { useState } from 'react';

const ControlPanel = ({ onLog }) => {
  const [instruction, setInstruction] = useState('测试选品');
  const [running, setRunning] = useState(false);
  const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

  const startPipeline = async () => {
    setRunning(true);
    try {
      const res = await fetch(`${API_URL}/api/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ instruction }),
      });
      const data = await res.json();
      console.log('Pipeline done:', data);
      if (onLog) onLog('Pipeline completed!');
    } catch (err) {
      console.error('Pipeline failed:', err);
      if (onLog) onLog('Error: ' + err.message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="bg-white p-6 rounded shadow">
      <h2 className="text-xl font-semibold mb-4">控制面板</h2>
      <input
        type="text"
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        className="border p-2 w-full mb-3 rounded"
        placeholder="输入选品指令..."
      />
      <button
        onClick={startPipeline}
        disabled={running}
        className={`px-6 py-2 rounded font-semibold text-white ${running ? 'bg-gray-400' : 'bg-blue-500 hover:bg-blue-600'}`}
      >
        {running ? '运行中...' : '启动流水线'}
      </button>
    </div>
  );
};

export default ControlPanel;
