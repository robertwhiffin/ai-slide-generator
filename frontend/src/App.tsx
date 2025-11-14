import { AppLayout } from './components/Layout/AppLayout';
import './index.css';
import { SelectionProvider } from './contexts/SelectionContext';

function App() {
  return (
    <SelectionProvider>
      <AppLayout />
    </SelectionProvider>
  );
}

export default App;
