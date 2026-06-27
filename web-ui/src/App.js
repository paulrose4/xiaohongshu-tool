import React from 'react';
import LogViewer from './components/LogViewer';
import TaskStatus from './components/TaskStatus';
import ControlPanel from './components/ControlPanel';

const App = () => {
  return (
    <div className="min-h-screen bg-gray-100">
      <header className="bg-blue-600 text-white p-4">
        <h1 className="text-2xl font-bold">小红书带货系统监控台</h1>
      </header>
      
      <main className="container mx-auto p-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <ControlPanel />
          <LogViewer />
        </div>
        
        <TaskStatus />
      </main>
    </div>
  );
};

export default App;