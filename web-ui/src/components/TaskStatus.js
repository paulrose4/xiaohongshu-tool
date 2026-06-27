import React from 'react';

const TaskStatus = () => {
  return (
    <div className="bg-white p-6 rounded shadow mt-4">
      <h2 className="text-xl font-semibold mb-4">任务状态</h2>
      <div className="space-y-2">
        <div className="flex justify-between">
          <span>当前状态:</span>
          <span className="font-mono">准备就绪</span>
        </div>
        <div className="flex justify-between">
          <span>进度:</span>
          <span className="font-mono">0%</span>
        </div>
      </div>
    </div>
  );
};

export default TaskStatus;