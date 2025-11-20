import { AppLayout } from './components/Layout/AppLayout';
import './index.css';
import { SelectionProvider } from './contexts/SelectionContext';
import { ProfileProvider } from './contexts/ProfileContext';

function App() {
  return (
    <ProfileProvider>
      <SelectionProvider>
        <AppLayout />
      </SelectionProvider>
    </ProfileProvider>
  );
}

export default App;
