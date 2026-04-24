import { Routes, Route, Navigate } from 'react-router-dom';
import { HomePage } from './pages/HomePage';
import { SimulatorPage } from './pages/SimulatorPage';
import { TweaksPage } from './pages/TweaksPage';

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/simulator" element={<SimulatorPage />} />
      <Route path="/tweaks" element={<TweaksPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default App;
